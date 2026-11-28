"""Comprehensive end-to-end tests for IMS multi-table specification architecture against PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from openpyxl import Workbook, load_workbook
import psycopg2
from psycopg2 import sql

import database_init
from ims import create_app
from ims.jalali import (
    format_jalali_date,
    format_jalali_datetime,
    gregorian_to_jalali,
    jalali_to_gregorian,
)


TEST_DB_NAME = "IMS_test_db"


def _make_xlsx_bytes(headers: list[str], rows: list[list]) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class IMSEndToEndTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_cfg = database_init.get_connection_kwargs()
        maint_cfg = database_init.get_maintenance_connection_kwargs()

        maint_conn = psycopg2.connect(**maint_cfg)
        maint_conn.autocommit = True
        try:
            with maint_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                      FROM pg_stat_activity
                     WHERE datname = %s AND pid <> pg_backend_pid();
                    """,
                    (TEST_DB_NAME,),
                )
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(TEST_DB_NAME)))
                cur.execute(
                    sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(sql.Identifier(TEST_DB_NAME))
                )
        finally:
            maint_conn.close()

        test_db_cfg = dict(cls.base_cfg)
        test_db_cfg["dbname"] = TEST_DB_NAME

        app_conn = psycopg2.connect(**test_db_cfg)
        try:
            with app_conn:
                with app_conn.cursor() as cur:
                    database_init.create_tables(cur)
                    database_init.create_triggers(cur)
                    database_init.seed_initial_data(cur)
        finally:
            app_conn.close()

        cls.tmp_instance = tempfile.mkdtemp(prefix="ims_test_instance_")
        os.environ["IMS_DB_NAME"] = TEST_DB_NAME
        cls.app = create_app({
            "TESTING": True,
            "INSTANCE_DIR": cls.tmp_instance,
            "DB_CONFIG": test_db_cfg,
        })
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        db = cls.app.extensions.get("db")
        if db:
            db.close()

        os.environ.pop("IMS_DB_NAME", None)
        shutil.rmtree(cls.tmp_instance, ignore_errors=True)

        maint_cfg = database_init.get_maintenance_connection_kwargs()
        maint_conn = psycopg2.connect(**maint_cfg)
        maint_conn.autocommit = True
        try:
            with maint_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                      FROM pg_stat_activity
                     WHERE datname = %s AND pid <> pg_backend_pid();
                    """,
                    (TEST_DB_NAME,),
                )
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(TEST_DB_NAME)))
        finally:
            maint_conn.close()

    def login_admin(self, client=None):
        c = client or self.client
        resp = c.post("/api/auth/login", json={"user_name": "admin", "password": "admin"})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()["user"]

    def _get_category_by_path(self, full_path: str) -> dict:
        cats = self.client.get("/api/categories").get_json()["categories"]
        matches = [c for c in cats if c["full_path"] == full_path]
        self.assertTrue(matches, f"Category '{full_path}' not found in { [c['full_path'] for c in cats] }")
        return matches[0]

    def _upload_and_import_type(
        self,
        item_type: str,
        xlsx_buf: BytesIO,
        filename: str,
        policy: str = "skip",
        mapping_override: dict | None = None,
    ) -> dict:
        up = self.client.post(
            "/api/import/upload",
            data={"file": (xlsx_buf, filename), "item_type": item_type},
            content_type="multipart/form-data",
        )
        self.assertEqual(up.status_code, 200, up.get_data(as_text=True))
        up_json = up.get_json()
        mapping = dict(up_json["suggested_mapping"])
        if mapping_override:
            mapping.update(mapping_override)

        conf = self.client.post(
            "/api/import/confirm",
            json={
                "upload_id": up_json["upload_id"],
                "item_type": item_type,
                "sheet_name": up_json["selected_sheet"],
                "column_mapping": mapping,
                "existing_policy": policy,
            },
        )
        self.assertEqual(conf.status_code, 200, conf.get_data(as_text=True))
        return conf.get_json()

    def test_01_authentication_and_users(self):
        self.assertEqual(self.client.get("/api/dashboard/summary").status_code, 401)
        page_resp = self.client.get("/")
        self.assertEqual(page_resp.status_code, 302)
        self.assertIn("/login", page_resp.headers["Location"])

        bad = self.client.post("/api/auth/login", json={"user_name": "admin", "password": "wrong"})
        self.assertEqual(bad.status_code, 401)

        user = self.login_admin()
        self.assertEqual(user["user_name"], "admin")
        self.assertEqual(user["role_name"], "admin")
        self.assertTrue(user["is_admin"])

        roles_resp = self.client.get("/api/roles")
        self.assertEqual(roles_resp.status_code, 200)
        role_names = {r["name"] for r in roles_resp.get_json()["roles"]}
        self.assertEqual(role_names, {"admin", "employee"})

        created = self.client.post(
            "/api/users",
            json={
                "first_name": "Sara",
                "last_name": "Engineer",
                "user_name": "sara",
                "password": "secret123",
            },
        )
        self.assertEqual(created.status_code, 201)
        sara = created.get_json()["user"]
        self.assertEqual(sara["role_name"], "employee")

        db = self.app.extensions["db"]
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT r.name
                  FROM user_role_assignment ura
                  JOIN role r ON r.id = ura.role_id
                 WHERE ura.user_id = %s;
                """,
                (sara["id"],),
            )
            self.assertEqual(cur.fetchone()["name"], "employee")

        self.client.post("/api/auth/logout")
        sara_login = self.client.post("/api/auth/login", json={"user_name": "sara", "password": "secret123"})
        self.assertEqual(sara_login.status_code, 200)
        self.assertEqual(sara_login.get_json()["user"]["role_name"], "employee")
        self.assertFalse(sara_login.get_json()["user"]["is_admin"])

        pw_upd = self.client.put(
            "/api/users/me/password",
            json={"current_password": "secret123", "new_password": "newpass456"},
        )
        self.assertEqual(pw_upd.status_code, 200)
        self.client.post("/api/auth/logout")
        self.assertEqual(
            self.client.post("/api/auth/login", json={"user_name": "sara", "password": "newpass456"}).status_code,
            200,
        )
        self.client.post("/api/auth/logout")
        self.login_admin()

    def test_02_empty_initial_categories_and_hierarchy_triggers(self):
        self.login_admin()
        cats = self.client.get("/api/categories").get_json()["categories"]
        self.assertEqual(cats, [])

        # Cycle protection via PostgreSQL trigger on a custom category hierarchy
        r_root = self.client.post("/api/categories", json={"name": "CustomRoot"})
        self.assertEqual(r_root.status_code, 201)
        root_id = r_root.get_json()["category"]["id"]

        r1 = self.client.post("/api/categories", json={"name": "CustomGroup", "parent_id": root_id})
        self.assertEqual(r1.status_code, 201)
        grp_id = r1.get_json()["category"]["id"]

        r2 = self.client.post("/api/categories", json={"name": "CustomLeaf", "parent_id": grp_id})
        self.assertEqual(r2.status_code, 201)
        leaf_id = r2.get_json()["category"]["id"]

        cyc = self.client.put(
            f"/api/categories/{grp_id}",
            json={"name": "CustomGroup", "parent_id": leaf_id},
        )
        self.assertEqual(cyc.status_code, 400)
        self.assertIn("cycle", cyc.get_json()["error"].lower())

        del_parent = self.client.delete(f"/api/categories/{grp_id}")
        self.assertEqual(del_parent.status_code, 409)

        self.assertEqual(self.client.delete(f"/api/categories/{leaf_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/categories/{grp_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/categories/{root_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/categories").get_json()["categories"], [])

    def test_03_multi_type_templates_and_excel_imports(self):
        self.login_admin()

        # Verify /api/items/spec-schema
        schema_resp = self.client.get("/api/items/spec-schema")
        self.assertEqual(schema_resp.status_code, 200)
        schema = schema_resp.get_json()
        self.assertEqual(
            schema["order"],
            ["electronic_item", "screw", "nut", "spacer", "washer", "o_ring"],
        )
        elec_fields = {f["name"]: f for f in schema["types"]["electronic_item"]["fields"]}
        self.assertIn("package_size", elec_fields)
        self.assertNotIn("size", elec_fields)

        screw_fields = {f["name"]: f for f in schema["types"]["screw"]["fields"]}
        self.assertEqual(
            [o["value"] for o in screw_fields["head_type"]["options"]],
            ["سرخزینه", "آلنی", "قارچی", "مغزی"],
        )
        self.assertEqual(
            [o["value"] for o in screw_fields["drive_type"]["options"]],
            ["چهارسو", "آلنی"],
        )

        # Download & verify all 6 Excel templates
        for item_type in schema["order"]:
            tpl = self.client.get(f"/api/import/template/{item_type}")
            self.assertEqual(tpl.status_code, 200, f"Template failed for {item_type}")
            wb = load_workbook(BytesIO(tpl.data))
            self.assertIn("Field Guide", wb.sheetnames)
            headers = [c.value for c in wb.active[1]]
            if item_type == "electronic_item":
                self.assertIn("package_size", headers)
            elif item_type == "o_ring":
                self.assertNotIn("cross_section", headers)
                self.assertIn("inner_diameter", headers)
                self.assertIn("outer_diameter", headers)

        # 1) Electronic import (9 valid rows + 1 invalid mounting 'SM', verifying custom column mapping)
        elec_wb_buf = _make_xlsx_bytes(
            ["part_code", "main_cat", "sub_category", "model", "footprint", "mounting_type", "voltage", "location", "quantity", "price"],
            [
                ["1001", "Electronic", "Resistor", "0.33R", "1206", "SM", None, "E1", 50, 2],      # invalid mounting_type 'SM'
                ["1002", "Electronic", "Resistor", "1.3R", "1206", "SMD", None, "E1", 90, 3],
                ["1003", "Electronic", "Resistor", "1.5K", "0805", "DIP", None, "E1", 60, 2],
                ["1004", "Electronic", "Capacitor", "100pF", "0603", "SMD", "50V", "E2", 20, 3],
                ["1005", "Electronic", "Capacitor", "10uF", "0805", "SMD", "25V", "E2", 40, 5],
                ["1006", "Electronic", "Diode", "1N4148", "SOD-123", "SMD", "75V", "E3", 100, 4],
                ["1007", "Electronic", "Relay", "SRD-05VDC", "THT", "DIP", "5V", "E4", 15, 12],
                ["1008", "Electronic", "Microcontroller", "STM32F4", "LQFP-64", "SMD", "3.3V", "E5", 10, 50],
                ["1009", "Electronic", "Resistor", "10K", "0603", "SMD", None, "E1", 120, 2],
                ["1010", "Electronic", "Capacitor", "100nF", "0603", "SMD", "50V", "E2", 200, 1],
            ],
        )
        elec_bytes = elec_wb_buf.getvalue()
        up = self.client.post(
            "/api/import/upload",
            data={"file": (BytesIO(elec_bytes), "electronic_batch.xlsx"), "item_type": "electronic_item"},
            content_type="multipart/form-data",
        )
        self.assertEqual(up.status_code, 200, up.get_data(as_text=True))
        up_json = up.get_json()
        self.assertEqual(up_json["total_data_rows"], 10)
        self.assertEqual(up_json["suggested_mapping"]["package_size"], "footprint")

        # Explicitly verify manual column assignment works for arbitrary column header names
        manual_mapping = dict(up_json["suggested_mapping"])
        manual_mapping["item_code"] = "part_code"
        manual_mapping["category"] = "main_cat"

        prev = self.client.post(
            "/api/import/preview",
            json={
                "upload_id": up_json["upload_id"],
                "item_type": "electronic_item",
                "sheet_name": up_json["selected_sheet"],
                "column_mapping": manual_mapping,
                "existing_policy": "skip",
            },
        ).get_json()
        self.assertEqual(prev["summary"]["valid_new_rows"], 9)
        self.assertEqual(prev["summary"]["invalid_rows"], 1)

        conf = self.client.post(
            "/api/import/confirm",
            json={
                "upload_id": up_json["upload_id"],
                "item_type": "electronic_item",
                "sheet_name": up_json["selected_sheet"],
                "column_mapping": manual_mapping,
                "existing_policy": "skip",
            },
        ).get_json()
        self.assertEqual(conf["summary"]["created_items"], 9)
        self.assertEqual(conf["summary"]["failed_rows"], 1)
        self.assertEqual(conf["summary"]["opening_transactions_created"], 9)

        item_1002 = self.client.get("/api/items?item_code=1002").get_json()["items"][0]
        self.assertEqual(item_1002["item_type"], "electronic_item")
        self.assertEqual(item_1002["quantity"], 90)
        self.assertAlmostEqual(item_1002["weighted_avg_cost"], 3.0)
        self.assertAlmostEqual(item_1002["last_purchase_cost"], 3.0)

        # Re-importing same file under 'skip' creates zero duplicates
        conf_skip = self._upload_and_import_type(
            "electronic_item",
            BytesIO(elec_bytes),
            "electronic_batch.xlsx",
            policy="skip",
            mapping_override={"item_code": "part_code", "category": "main_cat"},
        )
        self.assertEqual(conf_skip["summary"]["created_items"], 0)
        self.assertEqual(conf_skip["summary"]["skipped_items"], 9)

        # Re-importing under 'update_metadata' updates specs without touching stock
        conf_upd = self._upload_and_import_type(
            "electronic_item",
            BytesIO(elec_bytes),
            "electronic_batch.xlsx",
            policy="update_metadata",
            mapping_override={"item_code": "part_code", "category": "main_cat"},
        )
        self.assertEqual(conf_upd["summary"]["updated_items"], 9)
        self.assertEqual(conf_upd["summary"]["opening_transactions_created"], 0)

        # Custom Electronic edge cases: duplicate code, missing category, zero qty, nullable model + package_size
        edge_xlsx = _make_xlsx_bytes(
            ["item_code", "category", "sub_category", "model", "package_size", "location", "quantity", "price"],
            [
                ["DUP-1", "Electronics", "Diode", "1N4148", "DO-35", "A1", 10, 5000],
                ["DUP-1", "Electronics", "Diode", "1N4148", "DO-35", "A1", 20, 5000],
                ["NOCAT-1", "", "", "1N4007", "DO-41", "A2", 5, 1000],
                ["ZERO-1", "Electronics", "MCU", "STM32F103", "LQFP-48", "B1", 0, None],
                ["NOMODEL-IMP", "Electronics", "Diode", None, "0805", "A3", 5, 1000],
            ],
        )
        conf_edge = self._upload_and_import_type("electronic_item", edge_xlsx, "edge_elec.xlsx")
        self.assertEqual(conf_edge["summary"]["duplicate_rows"], 2)
        self.assertEqual(conf_edge["summary"]["invalid_or_missing_rows"], 1)
        self.assertEqual(conf_edge["summary"]["created_items"], 2)

        nomodel_imp = self.client.get("/api/items?item_code=NOMODEL-IMP").get_json()["items"][0]
        self.assertIsNone(nomodel_imp["specs"]["model"])
        self.assertEqual(nomodel_imp["specs"]["package_size"], "0805")
        self.assertEqual(nomodel_imp["quantity"], 5)

        zero_item = self.client.get("/api/items?item_code=ZERO-1").get_json()["items"][0]
        self.assertEqual(zero_item["quantity"], 0)
        self.assertIsNone(zero_item["weighted_avg_cost"])

        # 2) Screw import (valid Farsi head/drive + invalid M5 string rejected + Mechanical-in-Electronic blocked)
        screw_xlsx = _make_xlsx_bytes(
            ["item_code", "diameter", "length", "material", "head_type", "drive_type", "location", "quantity", "price"],
            [
                ["IMP-SCR-1", 4, 12, "STAINLESS_STEEL", "آلنی", "آلنی", "M1", 100, 15000],
                ["IMP-SCR-2", 3, 8, "BLACK", "قارچی", "چهارسو", "M1", 60, 12000],
                ["IMP-SCR-BAD", "M5", 10, "WHITE", "سرخزینه", "چهارسو", "M1", 10, 5000],
            ],
        )
        conf_scr = self._upload_and_import_type("screw", screw_xlsx, "screws.xlsx")
        self.assertEqual(conf_scr["summary"]["created_items"], 2)
        self.assertEqual(conf_scr["summary"]["failed_rows"], 1)
        scr1 = self.client.get("/api/items?item_code=IMP-SCR-1").get_json()["items"][0]
        self.assertEqual(scr1["item_type"], "screw")
        self.assertEqual(scr1["specs"]["head_type"], "آلنی")
        self.assertEqual(scr1["specs"]["drive_type"], "آلنی")
        self.assertAlmostEqual(float(scr1["specs"]["diameter"]), 4.0)

        # Cross-type update_metadata rejection: try updating existing screw IMP-SCR-1 via nut import
        wrong_type_xlsx = _make_xlsx_bytes(
            ["item_code", "diameter", "material", "location", "quantity", "price"],
            [["IMP-SCR-1", 4, "IRON", "M2", 10, 2000]],
        )
        conf_wrong = self._upload_and_import_type("nut", wrong_type_xlsx, "wrong_nut.xlsx", policy="update_metadata")
        self.assertEqual(conf_wrong["summary"]["updated_items"], 0)
        self.assertEqual(conf_wrong["summary"]["failed_rows"], 1)

        # 3) Nut, Spacer, Washer, and O-Ring imports (verify auto cross_section & outer<=inner rejection)
        nut_xlsx = _make_xlsx_bytes(
            ["item_code", "diameter", "material", "location", "quantity", "price"],
            [["IMP-NUT-1", 4, "IRON", "M2", 200, 5000]],
        )
        self.assertEqual(self._upload_and_import_type("nut", nut_xlsx, "nuts.xlsx")["summary"]["created_items"], 1)

        spacer_xlsx = _make_xlsx_bytes(
            ["item_code", "diameter", "length", "material", "spacer_type", "location", "quantity", "price"],
            [["IMP-SPC-1", 3, 15, "PLASTIC", "F", "M3", 80, 20000]],
        )
        self.assertEqual(self._upload_and_import_type("spacer", spacer_xlsx, "spacers.xlsx")["summary"]["created_items"], 1)

        washer_xlsx = _make_xlsx_bytes(
            ["item_code", "diameter", "material", "washer_type", "location", "quantity", "price"],
            [["IMP-WSH-1", 5, "STAINLESS_STEEL", "SPRING", "M4", 150, 4000]],
        )
        self.assertEqual(self._upload_and_import_type("washer", washer_xlsx, "washers.xlsx")["summary"]["created_items"], 1)

        oring_xlsx = _make_xlsx_bytes(
            ["item_code", "inner_diameter", "outer_diameter", "material", "location", "quantity", "price"],
            [
                ["IMP-ORG-1", 10, 16, "VITON", "M5", 40, 35000],
                ["IMP-ORG-BAD", 12, 10, "NBR", "M5", 10, 10000],
            ],
        )
        conf_org = self._upload_and_import_type("o_ring", oring_xlsx, "orings.xlsx")
        self.assertEqual(conf_org["summary"]["created_items"], 1)
        self.assertEqual(conf_org["summary"]["failed_rows"], 1)

        org1 = self.client.get("/api/items?item_code=IMP-ORG-1").get_json()["items"][0]
        self.assertAlmostEqual(float(org1["specs"]["cross_section"]), 3.0)

    def test_04_multi_type_crud_triggers_and_filters(self):
        self.login_admin()
        cat_elec = self._get_category_by_path("Electronic > Microcontroller")["id"]
        cat_screw = self._get_category_by_path("Mechanical > Screw")["id"]
        cat_oring = self._get_category_by_path("Mechanical > O-Ring")["id"]
        cat_mech_parent = self._get_category_by_path("Mechanical")["id"]

        # Reject non-leaf parent category on item creation
        non_leaf_resp = self.client.post(
            "/api/items",
            json={"item_code": "NONLEAF-1", "category_id": cat_mech_parent, "location": "L1", "specs": {}},
        )
        self.assertEqual(non_leaf_resp.status_code, 400)

        # Create O-Ring via API; cross_section must be computed by PostgreSQL regardless of payload
        org_resp = self.client.post(
            "/api/items",
            json={
                "item_code": "API-ORG-1",
                "category_id": cat_oring,
                "location": "S-1",
                "specs": {
                    "inner_diameter": 8,
                    "outer_diameter": 12.5,
                    "cross_section": 999,
                    "material": "SILICONE",
                },
            },
        )
        self.assertEqual(org_resp.status_code, 201, org_resp.get_data(as_text=True))
        org_item = org_resp.get_json()["item"]
        self.assertEqual(org_item["item_type"], "o_ring")
        self.assertAlmostEqual(float(org_item["specs"]["cross_section"]), 2.25)

        # Create Screw with Farsi head/drive values
        scr_resp = self.client.post(
            "/api/items",
            json={
                "item_code": "API-SCR-1",
                "category_id": cat_screw,
                "location": "S-2",
                "specs": {
                    "diameter": 5,
                    "length": 14,
                    "material": "WHITE",
                    "head_type": "مغزی",
                    "drive_type": "آلنی",
                },
            },
        )
        self.assertEqual(scr_resp.status_code, 201)
        scr_item = scr_resp.get_json()["item"]

        # PostgreSQL triggers must block wrong-type spec insert & duplicate spec table row
        db = self.app.extensions["db"]
        with db.connection() as conn:
            with conn.cursor() as cur:
                with self.assertRaises(psycopg2.errors.RaiseException):
                    cur.execute(
                        "INSERT INTO nut (item_id, diameter, material) VALUES (%s, 5, 'IRON');",
                        (scr_item["id"],),
                    )
                conn.rollback()

                with self.assertRaises(psycopg2.errors.RaiseException):
                    cur.execute(
                        "UPDATE item SET category_id = %s WHERE id = %s;",
                        (cat_elec, scr_item["id"]),
                    )
                conn.rollback()

                cur.execute(
                    "INSERT INTO item (item_code, category_id, location) VALUES ('TRIG-RAW', %s, 'T1') RETURNING id;",
                    (cat_elec,),
                )
                raw_elec_id = cur.fetchone()[0]
                with self.assertRaises(psycopg2.errors.RaiseException):
                    cur.execute(
                        "INSERT INTO screw (item_id, diameter, length) VALUES (%s, 3, 10);",
                        (raw_elec_id,),
                    )
                conn.rollback()

        # Cannot add child category under a populated leaf category
        bad_sub = self.client.post(
            "/api/categories",
            json={"name": "SubUnderScrew", "parent_id": cat_screw},
        )
        self.assertEqual(bad_sub.status_code, 409)

        # Numeric mm range filter + Farsi head_type filter
        filtered_screw = self.client.get(
            "/api/items?item_type=screw&min_length=13&max_length=15&head_type=مغزی"
        ).get_json()
        self.assertEqual(filtered_screw["total"], 1)
        self.assertEqual(filtered_screw["items"][0]["item_code"], "API-SCR-1")

        # O-Ring computed cross_section filter
        filtered_org = self.client.get("/api/items?item_type=o_ring&cross_section=3").get_json()
        self.assertEqual(filtered_org["total"], 1)
        self.assertEqual(filtered_org["items"][0]["item_code"], "IMP-ORG-1")

        # Electronic package_size filter
        filtered_elec = self.client.get("/api/items?item_type=electronic_item&package_size=0805").get_json()
        self.assertGreaterEqual(filtered_elec["total"], 1)

    def test_05_transactions_mixed_cart_concurrency_and_immutability(self):
        self.login_admin()
        cat_res = self._get_category_by_path("Electronic > Resistor")["id"]

        item_resp = self.client.post(
            "/api/items",
            json={
                "item_code": "TEST-WAC-1",
                "category_id": cat_res,
                "location": "C4",
                "specs": {
                    "model": "ATmega328P",
                    "package_size": "TQFP-32",
                    "mounting_type": "SMD",
                },
            },
        )
        self.assertEqual(item_resp.status_code, 201)
        item = item_resp.get_json()["item"]
        item_id = item["id"]

        no_price = self.client.post(
            "/api/transactions",
            json={"item_id": item_id, "transaction_type": "PURCHASE_IN", "quantity": 10},
        )
        self.assertEqual(no_price.status_code, 400)

        p1 = self.client.post(
            "/api/transactions",
            json={"item_id": item_id, "transaction_type": "PURCHASE_IN", "quantity": 100, "price": "2.00"},
        )
        self.assertEqual(p1.status_code, 201)
        p2 = self.client.post(
            "/api/transactions",
            json={"item_id": item_id, "transaction_type": "PURCHASE_IN", "quantity": 50, "price": "5.00"},
        )
        self.assertEqual(p2.status_code, 201)
        p2_data = p2.get_json()
        self.assertEqual(p2_data["inventory"]["current_quantity"], 150)
        self.assertAlmostEqual(p2_data["inventory"]["weighted_avg_cost"], 3.0)
        self.assertAlmostEqual(p2_data["inventory"]["last_purchase_cost"], 5.0)

        out_with_price = self.client.post(
            "/api/transactions",
            json={"item_id": item_id, "transaction_type": "OUT", "quantity": 10, "price": 1.0},
        )
        self.assertEqual(out_with_price.status_code, 400)

        out_ok = self.client.post(
            "/api/transactions",
            json={"item_id": item_id, "transaction_type": "OUT", "quantity": 30},
        )
        self.assertEqual(out_ok.status_code, 201)
        out_data = out_ok.get_json()
        self.assertEqual(out_data["transaction"]["stock_before"], 150)
        self.assertEqual(out_data["transaction"]["stock_after"], 120)
        self.assertAlmostEqual(out_data["transaction"]["unit_cost_snapshot"], 3.0)
        self.assertAlmostEqual(out_data["transaction"]["transaction_cost_snapshot"], 90.0)

        adj_out = self.client.post(
            "/api/transactions",
            json={"item_id": item_id, "transaction_type": "ADJUSTMENT_OUT", "quantity": 100},
        )
        self.assertEqual(adj_out.status_code, 201)
        self.assertEqual(adj_out.get_json()["inventory"]["current_quantity"], 20)

        # Mixed Electronic + Mechanical bulk cart with duplicate rows exceeding stock for TEST-WAC-1
        mech_item = self.client.get("/api/items?item_code=IMP-SCR-1").get_json()["items"][0]
        elec_other = self.client.get("/api/items?item_code=1003").get_json()["items"][0]
        bulk = self.client.post(
            "/api/transactions/bulk",
            json={
                "transaction_type": "OUT",
                "items": [
                    {"item_id": item_id, "quantity": 15},
                    {"item_id": item_id, "quantity": 15},
                    {"item_id": elec_other["id"], "quantity": 5},
                    {"item_id": mech_item["id"], "quantity": 10},
                ],
            },
        )
        self.assertEqual(bulk.status_code, 200)
        bulk_json = bulk.get_json()
        self.assertEqual(bulk_json["summary"]["succeeded"], 2)
        self.assertEqual(bulk_json["summary"]["failed"], 1)

        by_id = {r["item_id"]: r for r in bulk_json["results"]}
        self.assertEqual(by_id[item_id]["status"], "failed")
        self.assertEqual(by_id[item_id]["requested_quantity"], 30)
        self.assertEqual(by_id[mech_item["id"]]["status"], "succeeded")
        self.assertEqual(by_id[mech_item["id"]]["item_type"], "screw")

        def attempt_withdraw(_idx):
            with self.app.test_client() as tc:
                tc.post("/api/auth/login", json={"user_name": "admin", "password": "admin"})
                return tc.post(
                    "/api/transactions",
                    json={"item_id": item_id, "transaction_type": "OUT", "quantity": 6},
                ).status_code

        with ThreadPoolExecutor(max_workers=10) as pool:
            statuses = list(pool.map(attempt_withdraw, range(10)))

        self.assertEqual(statuses.count(201), 3)
        self.assertEqual(statuses.count(400), 7)

        detail = self.client.get(f"/api/items/{item_id}").get_json()["item"]
        self.assertEqual(detail["quantity"], 2)

        db = self.app.extensions["db"]
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM inventory_transaction LIMIT 1;")
                tx_id = cur.fetchone()[0]
                with self.assertRaises(psycopg2.errors.RaiseException):
                    cur.execute("UPDATE inventory_transaction SET quantity = 999 WHERE id = %s;", (tx_id,))
                conn.rollback()
                with self.assertRaises(psycopg2.errors.RaiseException):
                    cur.execute("DELETE FROM inventory_transaction WHERE id = %s;", (tx_id,))
                conn.rollback()

    def test_06_bom_calculator_mixed_read_only_and_incomplete_cost(self):
        self.login_admin()
        cat_res = self._get_category_by_path("Electronic > Resistor")["id"]

        unpriced = self.client.post(
            "/api/items",
            json={
                "item_code": "UNPRICED-1",
                "category_id": cat_res,
                "location": "Z9",
                "specs": {"model": "Mystery Header"},
            },
        ).get_json()["item"]
        self.client.post(
            "/api/transactions",
            json={"item_id": unpriced["id"], "transaction_type": "ADJUSTMENT_IN", "quantity": 50},
        )

        db = self.app.extensions["db"]
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM inventory_transaction;")
            tx_count_before = cur.fetchone()["c"]

        # Mixed Electronic + Mechanical BOM (1002 price 3 + IMP-ORG-1 price 35000 + 1004 price 3)
        bom_complete_xlsx = _make_xlsx_bytes(
            ["Item Code", "Quantity", "Item Name"],
            [
                ["1002", 5, "Res 1.3"],
                ["1002", 5, "Res 1.3"],       # merged => 10 * 3 = 30
                ["1004", 25, "Cap 100pF"],    # Insufficient (20), cost = 75
                ["IMP-ORG-1", 2, "O-Ring"],   # Mechanical available => 2 * 35000 = 70000
            ],
        )
        calc1 = self.client.post(
            "/api/bom/calculate",
            data={"file": (bom_complete_xlsx, "bom_ok.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(calc1.status_code, 200)
        j1 = calc1.get_json()
        self.assertTrue(j1["read_only"])
        self.assertEqual(j1["availability_summary"]["available"], 2)
        self.assertEqual(j1["availability_summary"]["insufficient"], 1)
        self.assertEqual(j1["availability_summary"]["merged_duplicate_rows"], 1)
        self.assertTrue(j1["cost_summary"]["wac_complete"])
        self.assertAlmostEqual(j1["cost_summary"]["wac_total"], 70105.0)

        exp_bom = self.client.post("/api/bom/export", json={"upload_id": j1["upload_id"]})
        self.assertEqual(exp_bom.status_code, 200)
        wb_bom = load_workbook(BytesIO(exp_bom.data))
        self.assertIn("BOM Cost Summary", wb_bom.sheetnames)
        self.assertIn("Inventory Availability", wb_bom.sheetnames)
        avail_headers = [c.value for c in wb_bom["Inventory Availability"][1]]
        self.assertIn("Item Type", avail_headers)
        self.assertIn("Specifications", avail_headers)

        bom_mixed_xlsx = _make_xlsx_bytes(
            ["Item Code", "Quantity"],
            [
                ["1002", 2],
                ["ZERO-1", 3],
                ["UNPRICED-1", 4],
                ["NO-SUCH-PART", 1],
                ["BAD-QTY", -5],
            ],
        )
        calc2 = self.client.post(
            "/api/bom/calculate",
            data={"file": (bom_mixed_xlsx, "bom_mixed.xlsx")},
            content_type="multipart/form-data",
        ).get_json()
        self.assertEqual(calc2["availability_summary"]["out_of_stock"], 1)
        self.assertEqual(calc2["availability_summary"]["unknown"], 1)
        self.assertEqual(calc2["availability_summary"]["invalid_rows"], 1)
        self.assertFalse(calc2["cost_summary"]["wac_complete"])
        self.assertIsNone(calc2["cost_summary"]["wac_total"])
        self.assertAlmostEqual(calc2["cost_summary"]["wac_known_subtotal"], 6.0)

        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM inventory_transaction;")
            tx_count_after = cur.fetchone()["c"]
        self.assertEqual(tx_count_before, tx_count_after)

    def test_07_exports_dashboard_analytics_and_pages(self):
        self.login_admin()

        dash = self.client.get("/api/dashboard/summary").get_json()
        m = dash["metrics"]
        self.assertNotIn("low_stock", m)
        self.assertNotIn("low_stock_count", m)
        self.assertFalse(m["wac_complete"])
        self.assertGreaterEqual(m["wac_missing_cost_items"], 1)
        self.assertGreaterEqual(m["zero_stock_count"], 1)
        self.assertEqual(len(dash["recent_movements"]), 5)
        self.assertEqual(len(dash["recent_items"]), 5)
        self.assertIn("item_type", dash["recent_items"][0])

        analytics = self.client.get("/api/reports/analytics")
        self.assertEqual(analytics.status_code, 200)

        # Single-type inventory export (Screws only -> 1 worksheet with Screw headers)
        exp_screw = self.client.get("/api/export/inventory?item_type=screw")
        self.assertEqual(exp_screw.status_code, 200)
        wb_scr = load_workbook(BytesIO(exp_screw.data))
        self.assertEqual(len(wb_scr.sheetnames), 1)
        scr_headers = [c.value for c in wb_scr.active[1]]
        self.assertIn("Diameter (mm)", scr_headers)
        self.assertIn("Head Type", scr_headers)

        # Multi-type inventory export -> multiple worksheets per present component type
        exp_all = self.client.get("/api/export/inventory")
        self.assertEqual(exp_all.status_code, 200)
        self.assertRegex(exp_all.headers["Content-Disposition"], r"inventory_report_\d{8}_\d{4}\.xlsx")
        wb_all = load_workbook(BytesIO(exp_all.data))
        self.assertGreaterEqual(len(wb_all.sheetnames), 6)
        self.assertIn("Electronic Items", wb_all.sheetnames)
        self.assertIn("O-Rings", wb_all.sheetnames)
        oring_headers = [c.value for c in wb_all["O-Rings"][1]]
        self.assertIn("Cross Section (mm)", oring_headers)
        elec_headers = [c.value for c in wb_all["Electronic Items"][1]]
        self.assertIn("Package Size", elec_headers)
        self.assertIn("Weighted Avg Cost (Rial)", elec_headers)
        self.assertIn("Total Value (WAC) (Toman)", elec_headers)
        self.assertIn("Updated At (Jalali)", elec_headers)

        # Transaction Excel export
        exp_tx = self.client.get("/api/export/transactions?transaction_type=OPENING")
        self.assertEqual(exp_tx.status_code, 200)
        wb_tx = load_workbook(BytesIO(exp_tx.data))
        tx_headers = [c.value for c in wb_tx.active[1]]
        self.assertIn("Item Type", tx_headers)
        self.assertIn("Specifications", tx_headers)
        self.assertIn("Timestamp (Jalali)", tx_headers)
        self.assertNotIn("Timestamp (UTC)", tx_headers)
        self.assertRegex(str(wb_tx.active.cell(row=2, column=2).value), r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$")

        # All UI routes load cleanly with HTTP 200 for admin
        for route in ("/", "/inventory", "/transactions/new", "/bom", "/transactions", "/reports", "/excel", "/users", "/settings"):
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 200, f"Route {route} returned {resp.status_code}")

        inv_html = self.client.get("/inventory").get_data(as_text=True)
        for token in ("f-item-type", "inv-spec-filters", "inv-more-filters-btn", "قیمت میانگین"):
            self.assertIn(token, inv_html)

        new_tx_html = self.client.get("/transactions/new").get_data(as_text=True)
        for token in (
            "tx-btn-new-item",
            "tx-btn-new-category",
            "tx-more-filters-btn",
            "tx-spec-filters",
            "tx-catalog-scroll",
            "tx-match-count",
            "t-item-type",
        ):
            self.assertIn(token, new_tx_html)
        for removed in ("t-desc", "t-min-qty", "t-max-qty", "tx-catalog-pagination"):
            self.assertNotIn(removed, new_tx_html)

        reports_html = self.client.get("/reports").get_data(as_text=True)
        for token in ("ex-item-type", "ex-spec-filters", "ex-preview-tbody", "scroll-table-8"):
            self.assertIn(token, reports_html)

        excel_html = self.client.get("/excel").get_data(as_text=True)
        self.assertIn("imp-cards-grid", excel_html)
        excel_js = self.client.get("/static/js/pages/excel.js").get_data(as_text=True)
        self.assertIn("/api/import/template/", excel_js)

        repo_root = Path(__file__).resolve().parent.parent / "ims"
        for ui_file in (*repo_root.joinpath("templates").rglob("*.html"), *repo_root.joinpath("static").rglob("*.js")):
            text = ui_file.read_text(encoding="utf-8")
            self.assertNotIn("میانگین موزون", text, f"Found deprecated term in {ui_file}")
            self.assertNotIn("میانگین موزود", text, f"Found deprecated term in {ui_file}")

        self.assertIn("badge-stock-accent", (repo_root / "static" / "css" / "components.css").read_text(encoding="utf-8"))
        self.assertIn("badge-stock-accent", (repo_root / "static" / "js" / "ui.js").read_text(encoding="utf-8"))

    def test_08_employee_rbac_restrictions(self):
        with self.app.test_client() as emp:
            login_r = emp.post("/api/auth/login", json={"user_name": "sara", "password": "newpass456"})
            self.assertEqual(login_r.status_code, 200)
            self.assertFalse(login_r.get_json()["user"]["is_admin"])

            self.assertEqual(emp.get("/excel").status_code, 403)
            self.assertEqual(emp.get("/api/import/template/screw").status_code, 403)
            self.assertEqual(emp.post("/api/import/upload").status_code, 403)
            self.assertEqual(emp.post("/api/import/inspect", json={}).status_code, 403)
            self.assertEqual(emp.post("/api/import/preview", json={}).status_code, 403)
            self.assertEqual(emp.post("/api/import/confirm", json={}).status_code, 403)

            self.assertEqual(emp.get("/users").status_code, 403)
            self.assertEqual(emp.get("/settings").status_code, 200)

            dash_html = emp.get("/").get_data(as_text=True)
            self.assertNotIn('href="/excel"', dash_html)
            self.assertNotIn('href="/users"', dash_html)
            self.assertIn('href="/settings"', dash_html)
            self.assertEqual(emp.get("/reports").status_code, 200)
            self.assertEqual(emp.get("/api/export/inventory").status_code, 200)
            self.assertEqual(emp.get("/api/items/spec-schema").status_code, 200)

            elec_id = self._get_category_by_path("Electronic")["id"]
            cat_add = emp.post("/api/categories", json={"name": "EmpCreatedSub", "parent_id": elec_id})
            self.assertEqual(cat_add.status_code, 201)
            cat_id = cat_add.get_json()["category"]["id"]
            self.assertEqual(emp.put(f"/api/categories/{cat_id}", json={"name": "Edited"}).status_code, 403)
            self.assertEqual(emp.delete(f"/api/categories/{cat_id}").status_code, 403)

            roles = emp.get("/api/roles").get_json()["roles"]
            for role in roles:
                bad_user = emp.post(
                    "/api/users",
                    json={
                        "first_name": "X",
                        "last_name": "Y",
                        "user_name": f"escalate_{role['id']}",
                        "password": "123",
                        "role_id": role["id"],
                    },
                )
                self.assertEqual(bad_user.status_code, 403)

        self.login_admin()
        self.assertEqual(self.client.delete(f"/api/categories/{cat_id}").status_code, 200)

    def test_09_jalali_calendar_and_multi_table_schema(self):
        self.login_admin()

        db = self.app.extensions["db"]
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name, is_nullable, is_generated
                  FROM information_schema.columns
                 WHERE table_schema = 'public';
                """
            )
            cols = {(r["table_name"], r["column_name"]): r for r in cur.fetchall()}

        self.assertEqual(cols[("app_user", "role_id")]["is_nullable"], "NO")
        self.assertEqual(cols[("electronic_item", "model")]["is_nullable"], "YES")
        self.assertIn(("electronic_item", "package_size"), cols)
        self.assertNotIn(("item", "model"), cols)
        self.assertEqual(cols[("o_ring", "cross_section")]["is_generated"], "ALWAYS")
        self.assertEqual(cols[("inventory_transaction", "created_at_jalali")]["is_nullable"], "NO")

        for tbl in ("electronic_item", "spacer", "screw", "nut", "washer", "o_ring"):
            self.assertTrue(any(t == tbl for t, _ in cols))

        self.assertEqual(gregorian_to_jalali(2025, 3, 20), (1403, 12, 30))
        self.assertEqual(jalali_to_gregorian(1403, 12, 30), (2025, 3, 20))
        self.assertEqual(gregorian_to_jalali(2026, 11, 23), (1405, 9, 2))

        sample_instants = (
            datetime(2025, 3, 19, 20, 30, 0, tzinfo=timezone.utc),
            datetime(2025, 3, 20, 20, 30, 0, tzinfo=timezone.utc),
            datetime(2026, 11, 23, 8, 45, 12, tzinfo=timezone.utc),
        )
        with db.cursor() as cur:
            for dt in sample_instants:
                cur.execute("SELECT fn_to_jalali_timestamp(%s::timestamptz) AS jts;", (dt,))
                self.assertEqual(cur.fetchone()["jts"], format_jalali_datetime(dt))

        cat_diode = self._get_category_by_path("Electronic > Diode")["id"]
        no_model_resp = self.client.post(
            "/api/items",
            json={
                "item_code": "NOMODEL-API",
                "category_id": cat_diode,
                "location": "D4",
                "specs": {"model": ""},
            },
        )
        self.assertEqual(no_model_resp.status_code, 201)
        no_model_item = no_model_resp.get_json()["item"]
        self.assertIsNone(no_model_item["specs"]["model"])

        tx_resp = self.client.post(
            "/api/transactions",
            json={
                "item_id": no_model_item["id"],
                "transaction_type": "OPENING",
                "quantity": 12,
                "price": "25000",
            },
        )
        self.assertEqual(tx_resp.status_code, 201)
        tx = tx_resp.get_json()["transaction"]
        self.assertRegex(tx["created_at_jalali"], r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$")

        today_j = format_jalali_date()
        res_today = self.client.get(f"/api/transactions?date_from={today_j}&date_to={today_j}")
        self.assertEqual(res_today.status_code, 200)
        self.assertGreaterEqual(res_today.get_json()["total"], 10)

        res_old = self.client.get("/api/transactions?date_from=1390/01/01&date_to=1390/01/02")
        self.assertEqual(res_old.status_code, 200)
        self.assertEqual(res_old.get_json()["total"], 0)

        res_invalid_date = self.client.get("/api/transactions?date_from=1405/12/30")
        self.assertEqual(res_invalid_date.status_code, 400)

        bom_null = _make_xlsx_bytes(["Item Code", "Quantity"], [["NOMODEL-API", 3]])
        bom_resp = self.client.post(
            "/api/bom/calculate",
            data={"file": (bom_null, "bom_nomodel.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(bom_resp.status_code, 200)
        self.assertEqual(bom_resp.get_json()["availability_summary"]["available"], 1)

        non_open_resp = self.client.get(
            "/api/transactions?transaction_type=PURCHASE_IN,OUT,ADJUSTMENT_IN,ADJUSTMENT_OUT"
        )
        self.assertEqual(non_open_resp.status_code, 200)
        non_open_data = non_open_resp.get_json()
        self.assertGreaterEqual(non_open_data["total"], 1)
        self.assertTrue(all(t["transaction_type"] != "OPENING" for t in non_open_data["transactions"]))

    def test_10_multilingual_excel_categories_and_category_spec_type(self):
        self.login_admin()

        # 1) Import Screws using Persian ("مکانیک" > "پیچ"), mixed ("Mechanical" > "پیچ آلنی"),
        # and lowercase English ("mechanical" > "screw" reusing seeded Mechanical > Screw).
        fa_screw_xlsx = _make_xlsx_bytes(
            ["کد قطعه", "دسته بندی", "زیر دسته", "diameter", "length", "material", "head_type", "drive_type", "محل نگهداری", "تعداد", "قیمت"],
            [
                ["FA-SCR-1", "مکانیک", "پیچ", 4, 12, "استیل ضدزنگ", "آلنی", "آلنی", "P-1", 50, 15000],
                ["MIX-SCR-1", "Mechanical", "پیچ آلنی", 3, 10, "مشکی", "آلنی", "آلنی", "P-2", 40, 10000],
                ["EN-SCR-1", "mechanical", "screw", 5, 20, "سفید", "قارچی", "چهارسو", "P-3", 30, 18000],
            ],
        )
        conf_scr = self._upload_and_import_type("screw", fa_screw_xlsx, "fa_screws.xlsx")
        self.assertEqual(conf_scr["summary"]["created_items"], 3, conf_scr)
        self.assertEqual(conf_scr["summary"]["failed_rows"], 0)

        fa_scr_item = self.client.get("/api/items?item_code=FA-SCR-1").get_json()["items"][0]
        self.assertEqual(fa_scr_item["category_path"], "مکانیک > پیچ")
        self.assertEqual(fa_scr_item["item_type"], "screw")
        self.assertEqual(fa_scr_item["specs"]["material"], "STAINLESS_STEEL")

        mix_scr_item = self.client.get("/api/items?item_code=MIX-SCR-1").get_json()["items"][0]
        self.assertEqual(mix_scr_item["category_path"], "Mechanical > پیچ آلنی")
        self.assertEqual(mix_scr_item["item_type"], "screw")
        self.assertEqual(mix_scr_item["specs"]["material"], "BLACK")

        # 2) Import Washers using Persian ("مکانیک" > "واشر") and Persian enum values
        fa_washer_xlsx = _make_xlsx_bytes(
            ["item_code", "category", "sub_category", "diameter", "washer_type", "material", "location", "quantity", "price"],
            [["FA-WSH-1", "مکانیک", "واشر", 5, "فنری", "استیل", "P-4", 120, 4500]],
        )
        conf_wsh = self._upload_and_import_type("washer", fa_washer_xlsx, "fa_washers.xlsx")
        self.assertEqual(conf_wsh["summary"]["created_items"], 1, conf_wsh)
        wsh_item = self.client.get("/api/items?item_code=FA-WSH-1").get_json()["items"][0]
        self.assertEqual(wsh_item["category_path"], "مکانیک > واشر")
        self.assertEqual(wsh_item["specs"]["washer_type"], "SPRING")
        self.assertEqual(wsh_item["specs"]["material"], "STAINLESS_STEEL")

        # 3) Import Electronic items using Persian ("قطعات الکترونیکی" > "مقاومت")
        fa_elec_xlsx = _make_xlsx_bytes(
            ["item_code", "category", "sub_category", "model", "package_size", "mounting_type", "location", "quantity", "price"],
            [["FA-RES-1", "قطعات الکترونیکی", "مقاومت", "10K 1%", "0603", "SMD", "E-FA", 200, 1200]],
        )
        conf_elec = self._upload_and_import_type("electronic_item", fa_elec_xlsx, "fa_elec.xlsx")
        self.assertEqual(conf_elec["summary"]["created_items"], 1, conf_elec)
        res_item = self.client.get("/api/items?item_code=FA-RES-1").get_json()["items"][0]
        self.assertEqual(res_item["category_path"], "قطعات الکترونیکی > مقاومت")
        self.assertEqual(res_item["item_type"], "electronic_item")

        # 4) Reject reusing existing "مکانیک > پیچ" (spec_type='screw') inside a Nut Excel import & SQL insert
        conflict_nut_xlsx = _make_xlsx_bytes(
            ["item_code", "category", "sub_category", "diameter", "material", "location", "quantity", "price"],
            [["CONFLICT-NUT-1", "مکانیک", "پیچ", 4, "IRON", "P-5", 10, 5000]],
        )
        up_conflict = self.client.post(
            "/api/import/upload",
            data={"file": (conflict_nut_xlsx, "conflict_nut.xlsx"), "item_type": "nut"},
            content_type="multipart/form-data",
        ).get_json()
        prev_conflict = self.client.post(
            "/api/import/preview",
            json={
                "upload_id": up_conflict["upload_id"],
                "item_type": "nut",
                "sheet_name": up_conflict["selected_sheet"],
                "column_mapping": up_conflict["suggested_mapping"],
            },
        ).get_json()
        self.assertEqual(prev_conflict["summary"]["invalid_rows"], 1)
        self.assertIn("already assigned to 'screw'", prev_conflict["rows"][0]["errors"][0])

        db = self.app.extensions["db"]
        with db.connection() as conn:
            with conn.cursor() as cur:
                with self.assertRaises(psycopg2.errors.RaiseException):
                    cur.execute(
                        "INSERT INTO nut (item_id, diameter, material) VALUES (%s, 4, 'IRON');",
                        (fa_scr_item["id"],),
                    )
                conn.rollback()

        # 5) Manual category creation with explicit Persian name + spec_type, safe rename of populated category,
        # and blocking spec_type change on populated category.
        custom_root = self.client.post("/api/categories", json={"name": "تجهیزات دستی"}).get_json()["category"]
        custom_leaf_resp = self.client.post(
            "/api/categories",
            json={"name": "اورینگ سیلیکونی", "parent_id": custom_root["id"], "spec_type": "o_ring"},
        )
        self.assertEqual(custom_leaf_resp.status_code, 201)
        custom_leaf = custom_leaf_resp.get_json()["category"]
        self.assertEqual(custom_leaf["spec_type"], "o_ring")

        custom_org = self.client.post(
            "/api/items",
            json={
                "item_code": "FA-ORG-MANUAL",
                "category_id": custom_leaf["id"],
                "location": "P-6",
                "specs": {"inner_diameter": 6, "outer_diameter": 10, "material": "سیلیکون"},
            },
        )
        self.assertEqual(custom_org.status_code, 201)
        self.assertAlmostEqual(float(custom_org.get_json()["item"]["specs"]["cross_section"]), 2.0)

        # Renaming populated leaf while keeping spec_type succeeds
        rename_ok = self.client.put(
            f"/api/categories/{custom_leaf['id']}",
            json={"name": "اورینگ نسوز", "parent_id": custom_root["id"], "spec_type": "o_ring"},
        )
        self.assertEqual(rename_ok.status_code, 200)
        self.assertEqual(rename_ok.get_json()["category"]["name"], "اورینگ نسوز")

        # Changing spec_type of populated leaf is rejected
        change_spec_bad = self.client.put(
            f"/api/categories/{custom_leaf['id']}",
            json={"name": "اورینگ نسوز", "parent_id": custom_root["id"], "spec_type": "nut"},
        )
        self.assertEqual(change_spec_bad.status_code, 409)


if __name__ == "__main__":
    unittest.main()
