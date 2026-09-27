import csv, gzip, json, subprocess, sys, unittest
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import billtree  # noqa: E402

LEGACY = ["lineItem/UsageAccountId", "lineItem/ProductCode", "product/region", "lineItem/ResourceId", "lineItem/UnblendedCost"]


class BillTreeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def write(self, name, header, rows, gz=False):
        p = self.tmp / name
        fh = gzip.open(p, "wt", newline="") if gz else open(p, "w", newline="")
        with fh:
            w = csv.writer(fh); w.writerow(header); w.writerows(rows)
        return p

    def test_legacy_and_v2_and_gzip_sum_exactly(self):
        self.write("a.csv", LEGACY, [["1", "AmazonEC2", "us-east-1", "i-1", "2.5"], ["1", "AmazonEC2", "us-east-1", "i-1", "1.5"],
                                      ["1", "AmazonS3", "", "", "0.25"], ["1", "Tax", "", "", "bad"]])
        self.write("b.csv.gz", list(billtree.COLUMNS["account"][:1]) + ["line_item_product_code", "product_region_code", "line_item_resource_id", "line_item_unblended_cost"],
                   [["2", "AWSLambda", "eu-west-1", "fn-x", "10"], ["2", "AWSLambda", "eu-west-1", "fn-x", "0"]], gz=True)
        costs, stats = billtree.aggregate(billtree.find_files([str(self.tmp)]))
        self.assertEqual(stats["files"], 2)
        self.assertEqual(stats["skipped"], 1)
        self.assertAlmostEqual(sum(costs.values()), 14.25)
        self.assertEqual(costs[("1", "AmazonEC2", "us-east-1", "i-1")], 4.0)
        self.assertIn(("1", "AmazonS3", billtree.NO_REGION, billtree.NO_RESOURCE), costs)
        tree = billtree.build_tree(costs)
        self.assertAlmostEqual(tree["cost"], 14.25)
        self.assertAlmostEqual(tree["children"]["2"]["children"]["AWSLambda"]["cost"], 10.0)

    def test_not_a_cur_file(self):
        self.write("x.csv", ["foo", "bar"], [["1", "2"]])
        with self.assertRaises(SystemExit):
            billtree.aggregate([self.tmp / "x.csv"])

    def test_json_fold_and_html(self):
        rows = [["1", "AmazonEC2", "us-east-1", f"i-{k}", str(k + 1)] for k in range(40)]
        p = self.write("c.csv", LEGACY, rows)
        out = subprocess.run([sys.executable, str(ROOT / "billtree.py"), str(p), "--json", str(self.tmp / "o.json"),
                              "--json-top", "5", "--html", str(self.tmp / "o.html")], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        doc = json.loads((self.tmp / "o.json").read_text())
        self.assertEqual(doc["total"], sum(range(1, 41)))
        region = doc["tree"]["children"][0]["children"][0]["children"][0]
        self.assertEqual(len(region["children"]), 6)
        self.assertEqual(region["children"][-1]["name"], "(35 more)")
        self.assertEqual(sum(c["cost"] for c in region["children"]), doc["total"])
        self.assertEqual(doc["top_resources"][0]["resource"], "i-39")
        self.assertIn("<svg", (self.tmp / "o.html").read_text())

    def test_squarify_area_preserved(self):
        rects = billtree.squarify([("a", 6, 0), ("b", 3, 0), ("c", 1, 0)], 0, 0, 100, 50)
        self.assertAlmostEqual(sum(w * h for _, _, _, w, h, _ in rects), 5000)
        self.assertAlmostEqual(rects[0][3] * rects[0][4], 3000)


if __name__ == "__main__":
    unittest.main()
