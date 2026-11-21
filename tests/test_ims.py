"""Comprehensive end-to-end tests for IMS against a real isolated PostgreSQL test database."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
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

    def test_01_authentication_and_users(self):
        # Unauthenticated requests blocked
        self.assertEqual(self.client.get("/api/dashboard/summary").status_code, 401)
        page_resp = self.client.get("/")
        self.assertEqual(page_resp.status_code, 302)
        self.assertIn("/login", page_resp.headers["Location"])

        # Bad password rejected
        bad = self.client.post("/api/auth/login", json={"user_name": "admin", "password": "wrong"})
        self.assertEqual(bad.status_code, 401)

        # Valid login
        user = self.login_admin()
        self.assertEqual(user["user_name"], "admin")

        # Create user (plaintext password stored per requirement)
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

        # Sign out, sign in as new user, change password, verify
        self.client.post("/api/auth/logout")
        self.assertEqual(
            self.client.post("/api/auth/login", json={"user_name": "sara", "password": "secret123"}).status_code,
            200,
        )
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

    def test_02_category_hierarchy_and_cycle_trigger(self):
        self.login_admin()
        r1 = self.client.post("/api/categories", json={"name": "Mechanical"})
        self.assertEqual(r1.status_code, 201)
        mech_id = r1.get_json()["category"]["id"]

        r2 = self.client.post("/api/categories", json={"name": "Fasteners", "parent_id": mech_id})
        self.assertEqual(r2.status_code, 201)
        fast_id = r2.get_json()["category"]["id"]

        # Cycle protection via PostgreSQL trigger: Mechanical -> Fasteners -> Mechanical
        cyc = self.client.put(f"/api/categories/{mech_id}", json={"name": "Mechanical", "parent_id": fast_id})
        self.assertEqual(cyc.status_code, 400)
        self.assertIn("cycle", cyc.get_json()["error"].lower())

        # Cannot delete parent category while child exists
        del_parent = self.client.delete(f"/api/categories/{mech_id}")
        self.assertEqual(del_parent.status_code, 409)

        # Clean up leaf then parent
        self.assertEqual(self.client.delete(f"/api/categories/{fast_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/categories/{mech_id}").status_code, 200)

    def test_03_import_sample_data_and_prevent_duplicates(self):
        self.login_admin()
        sample_path = Path(__file__).resolve().parent.parent / "data" / "sample_data.xlsx"
        with sample_path.open("rb") as fh:
            up = self.client.post(
                "/api/import/upload",
                data={"file": (fh, "sample_data.xlsx")},
                content_type="multipart/form-data",
            )
        self.assertEqual(up.status_code, 200, up.get_data(as_text=True))
        up_json = up.get_json()
        upload_id = up_json["upload_id"]
        self.assertEqual(up_json["total_data_rows"], 10)

        # Preview should flag row 2 (item 1001, mounting_type='SM') invalid, and 9 rows new
        prev = self.client.post(
            "/api/import/preview",
            json={
                "upload_id": upload_id,
                "sheet_name": up_json["selected_sheet"],
                "column_mapping": up_json["suggested_mapping"],
                "existing_policy": "skip",
            },
        )
        self.assertEqual(prev.status_code, 200)
        prev_json = prev.get_json()
        self.assertEqual(prev_json["summary"]["total_rows"], 10)
        self.assertEqual(prev_json["summary"]["valid_new_rows"], 9)
        self.assertEqual(prev_json["summary"]["invalid_rows"], 1)
        self.assertEqual(prev_json["summary"]["categories_to_create"], 1)
        self.assertGreaterEqual(prev_json["summary"]["subcategories_to_create"], 5)

        # Confirm import
        conf = self.client.post(
            "/api/import/confirm",
            json={
                "upload_id": upload_id,
                "sheet_name": up_json["selected_sheet"],
                "column_mapping": up_json["suggested_mapping"],
                "existing_policy": "skip",
            },
        )
        self.assertEqual(conf.status_code, 200, conf.get_data(as_text=True))
        conf_json = conf.get_json()
        self.assertEqual(conf_json["summary"]["created_items"], 9)
        self.assertEqual(conf_json["summary"]["failed_rows"], 1)
        self.assertEqual(conf_json["summary"]["opening_transactions_created"], 9)

        # Verify OPENING populated BOTH weighted_avg_cost AND last_purchase_cost!
        item_res = self.client.get("/api/items?item_code=1002").get_json()["items"][0]
        self.assertEqual(item_res["quantity"], 90)
        self.assertAlmostEqual(item_res["weighted_avg_cost"], 3.0)
        self.assertAlmostEqual(item_res["last_purchase_cost"], 3.0)

        # Re-importing the same file under default 'skip' creates zero duplicates
        with sample_path.open("rb") as fh:
            up2 = self.client.post(
                "/api/import/upload",
                data={"file": (fh, "sample_data.xlsx")},
                content_type="multipart/form-data",
            ).get_json()
        conf2 = self.client.post(
            "/api/import/confirm",
            json={
                "upload_id": up2["upload_id"],
                "sheet_name": up2["selected_sheet"],
                "column_mapping": up2["suggested_mapping"],
                "existing_policy": "skip",
            },
        ).get_json()
        self.assertEqual(conf2["summary"]["created_items"], 0)
        self.assertEqual(conf2["summary"]["skipped_items"], 9)
        self.assertEqual(conf2["summary"]["opening_transactions_created"], 0)

        # Re-importing under 'update_metadata' updates specs only without changing stock
        with sample_path.open("rb") as fh:
            up3 = self.client.post(
                "/api/import/upload",
                data={"file": (fh, "sample_data.xlsx")},
                content_type="multipart/form-data",
            ).get_json()
        conf3 = self.client.post(
            "/api/import/confirm",
            json={
                "upload_id": up3["upload_id"],
                "sheet_name": up3["selected_sheet"],
                "column_mapping": up3["suggested_mapping"],
                "existing_policy": "update_metadata",
            },
        ).get_json()
        self.assertEqual(conf3["summary"]["updated_items"], 9)
        self.assertEqual(conf3["summary"]["opening_transactions_created"], 0)
        item_after = self.client.get("/api/items?item_code=1002").get_json()["items"][0]
        self.assertEqual(item_after["quantity"], 90)

        # Custom workbook testing: duplicate codes in file, missing category, zero-qty item
        custom_xlsx = _make_xlsx_bytes(
            ["item_code", "category", "sub_category", "model", "location", "quantity", "price"],
            [
                ["DUP-1", "Electronics", "Diode", "1N4148", "A1", 10, 0.5],
                ["DUP-1", "Electronics", "Diode", "1N4148", "A1", 20, 0.5],
                ["NOCAT-1", "", "Diode", "1N4007", "A2", 5, 1.0],
                ["ZERO-1", "Electronics", "MCU", "STM32F103", "B1", 0, None],
            ],
        )
        up4 = self.client.post(
            "/api/import/upload",
            data={"file": (custom_xlsx, "edge.xlsx")},
            content_type="multipart/form-data",
        ).get_json()
        conf4 = self.client.post(
            "/api/import/confirm",
            json={
                "upload_id": up4["upload_id"],
                "sheet_name": up4["selected_sheet"],
                "column_mapping": up4["suggested_mapping"],
            },
        ).get_json()
        self.assertEqual(conf4["summary"]["duplicate_rows"], 2)
        self.assertEqual(conf4["summary"]["missing_category_rows"], 1)
        self.assertEqual(conf4["summary"]["created_items"], 1)
        self.assertEqual(conf4["summary"]["opening_transactions_created"], 0)

        zero_item = self.client.get("/api/items?item_code=ZERO-1").get_json()["items"][0]
        self.assertEqual(zero_item["quantity"], 0)
        self.assertIsNone(zero_item["weighted_avg_cost"])
        self.assertIsNone(zero_item["last_purchase_cost"])

    def test_04_transactions_wac_cart_concurrency_and_immutability(self):
        self.login_admin()
        # Pick Electronics > Resistor category
        cats = self.client.get("/api/categories").get_json()["categories"]
        cat_id = cats[-1]["id"]

        # Create item -> trigger automatically creates empty inventory row
        item_resp = self.client.post(
            "/api/items",
            json={
                "item_code": "TEST-WAC-1",
                "category_id": cat_id,
                "model": "ATmega328P",
                "size": "TQFP-32",
                "mounting_type": "SMD",
                "location": "C4",
            },
        )
        self.assertEqual(item_resp.status_code, 201)
        item = item_resp.get_json()["item"]
        item_id = item["id"]
        self.assertEqual(item["quantity"], 0)
        self.assertIsNone(item["weighted_avg_cost"])

        # PURCHASE_IN without price must fail
        no_price = self.client.post(
            "/api/transactions",
            json={"item_id": item_id, "transaction_type": "PURCHASE_IN", "quantity": 10},
        )
        self.assertEqual(no_price.status_code, 400)

        # Purchase 100 @ 2.00 then 50 @ 5.00 => WAC = (200 + 250)/150 = 3.00, LPC = 5.00
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

        # OUT with explicit price must fail
        out_with_price = self.client.post(
            "/api/transactions",
            json={"item_id": item_id, "transaction_type": "OUT", "quantity": 10, "price": 1.0},
        )
        self.assertEqual(out_with_price.status_code, 400)

        # Valid OUT 30 -> stock 120, unit_cost_snapshot=3.0, transaction_cost_snapshot=90.0
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
        self.assertAlmostEqual(out_data["inventory"]["weighted_avg_cost"], 3.0)
        self.assertAlmostEqual(out_data["inventory"]["last_purchase_cost"], 5.0)

        # ADJUSTMENT_OUT 100 -> stock left = 20
        adj_out = self.client.post(
            "/api/transactions",
            json={"item_id": item_id, "transaction_type": "ADJUSTMENT_OUT", "quantity": 100},
        )
        self.assertEqual(adj_out.status_code, 201)
        self.assertEqual(adj_out.get_json()["inventory"]["current_quantity"], 20)

        # Duplicate cart rows exceeding stock (15 + 15 = 30 > 20) must be aggregated & rejected,
        # while another valid item in the same bulk cart succeeds independently!
        other_item_id = self.client.get("/api/items?item_code=1003").get_json()["items"][0]["id"]
        bulk = self.client.post(
            "/api/transactions/bulk",
            json={
                "transaction_type": "OUT",
                "items": [
                    {"item_id": item_id, "quantity": 15},
                    {"item_id": item_id, "quantity": 15},
                    {"item_id": other_item_id, "quantity": 5},
                ],
            },
        )
        self.assertEqual(bulk.status_code, 200)
        bulk_json = bulk.get_json()
        self.assertEqual(bulk_json["summary"]["succeeded"], 1)
        self.assertEqual(bulk_json["summary"]["failed"], 1)

        by_id = {r["item_id"]: r for r in bulk_json["results"]}
        self.assertEqual(by_id[item_id]["status"], "failed")
        self.assertEqual(by_id[item_id]["requested_quantity"], 30)
        self.assertIn("Insufficient stock", by_id[item_id]["error"])
        self.assertEqual(by_id[other_item_id]["status"], "succeeded")

        # Concurrent OUT transactions on TEST-WAC-1 (stock=20): 10 threads each try OUT 6 -> max 3 succeed
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

        # Verify historical transactions are strictly immutable at PostgreSQL trigger level
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

    def test_05_bom_calculator_read_only_and_incomplete_cost(self):
        self.login_admin()
        cats = self.client.get("/api/categories").get_json()["categories"]
        cat_id = cats[0]["id"]

        # Add an unpriced stocked item (ADJUSTMENT_IN without price -> NULL cost)
        unpriced = self.client.post(
            "/api/items",
            json={
                "item_code": "UNPRICED-1",
                "category_id": cat_id,
                "model": "Mystery Header",
                "location": "Z9",
            },
        ).get_json()["item"]
        self.client.post(
            "/api/transactions",
            json={"item_id": unpriced["id"], "transaction_type": "ADJUSTMENT_IN", "quantity": 50},
        )

        # Snapshot counts before BOM calculation (must remain strictly identical)
        db = self.app.extensions["db"]
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM inventory_transaction;")
            tx_count_before = cur.fetchone()["c"]

        # 1) Complete BOM with duplicate rows merged
        bom_complete_xlsx = _make_xlsx_bytes(
            ["Item Code", "Quantity", "Item Name"],
            [
                ["1002", 5, "Res 1.3"],   # stock 90, price 3
                ["1002", 5, "Res 1.3"],   # merged => req 10 => cost 30
                ["1004", 25, "Cap 100pF"], # stock 20 (Insufficient!), price 3 => cost 75
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
        self.assertEqual(j1["availability_summary"]["available"], 1)
        self.assertEqual(j1["availability_summary"]["insufficient"], 1)
        self.assertEqual(j1["availability_summary"]["merged_duplicate_rows"], 1)
        self.assertTrue(j1["cost_summary"]["wac_complete"])
        self.assertTrue(j1["cost_summary"]["lpc_complete"])
        self.assertAlmostEqual(j1["cost_summary"]["wac_total"], 105.0)
        self.assertAlmostEqual(j1["cost_summary"]["lpc_total"], 105.0)

        # Export BOM Excel
        exp_bom = self.client.post("/api/bom/export", json={"upload_id": j1["upload_id"]})
        self.assertEqual(exp_bom.status_code, 200)
        wb_bom = load_workbook(BytesIO(exp_bom.data))
        self.assertIn("BOM Cost Summary", wb_bom.sheetnames)
        self.assertIn("Inventory Availability", wb_bom.sheetnames)

        # 2) BOM with unknown item, out-of-stock item, unpriced item, and invalid row
        bom_mixed_xlsx = _make_xlsx_bytes(
            ["Item Code", "Quantity"],
            [
                ["1002", 2],         # cost 6
                ["ZERO-1", 3],       # Out of Stock + NULL cost
                ["UNPRICED-1", 4],   # Available + NULL cost
                ["NO-SUCH-PART", 1], # Unknown
                ["BAD-QTY", -5],     # Invalid row
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

        # Verify zero transactions created by BOM module
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM inventory_transaction;")
            tx_count_after = cur.fetchone()["c"]
        self.assertEqual(tx_count_before, tx_count_after)

    def test_06_exports_dashboard_analytics_and_pages(self):
        self.login_admin()

        # Dashboard metrics (must show incomplete valuations due to UNPRICED-1 and NO low_stock key)
        dash = self.client.get("/api/dashboard/summary").get_json()
        m = dash["metrics"]
        self.assertNotIn("low_stock", m)
        self.assertNotIn("low_stock_count", m)
        self.assertFalse(m["wac_complete"])
        self.assertGreaterEqual(m["wac_missing_cost_items"], 1)
        self.assertGreaterEqual(m["zero_stock_count"], 1)

        # Analytics endpoint
        analytics = self.client.get("/api/reports/analytics")
        self.assertEqual(analytics.status_code, 200)
        self.assertTrue(len(analytics.get_json()["category_breakdown"]) >= 1)

        # Filtered Inventory Excel Export (e.g. SMD only)
        exp_inv = self.client.get("/api/export/inventory?mounting_type=SMD")
        self.assertEqual(exp_inv.status_code, 200)
        wb_inv = load_workbook(BytesIO(exp_inv.data))
        ws_inv = wb_inv.active
        headers = [cell.value for cell in ws_inv[1]]
        self.assertIn("Item Code", headers)
        self.assertIn("Total Value (WAC)", headers)
        self.assertGreaterEqual(ws_inv.max_row, 4)

        # Filtered Transaction Excel Export
        exp_tx = self.client.get("/api/export/transactions?transaction_type=OPENING")
        self.assertEqual(exp_tx.status_code, 200)
        wb_tx = load_workbook(BytesIO(exp_tx.data))
        self.assertGreaterEqual(wb_tx.active.max_row, 10)

        # All UI routes load cleanly with HTTP 200
        for route in ("/", "/inventory", "/transactions/new", "/bom", "/transactions", "/reports", "/excel", "/users"):
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 200, f"Route {route} returned {resp.status_code}")


if __name__ == "__main__":
    unittest.main()
