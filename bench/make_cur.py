#!/usr/bin/env python3
"""Write a synthetic CUR 2.0 month (hourly line items) for benchmarking. Prints the exact total."""
import csv, gzip, random, sys

def main(path, rows, seed=7):
    rnd = random.Random(seed)
    services = {"AmazonEC2": ("i-", 900), "AmazonRDS": ("db-", 60), "AmazonS3": ("bucket-", 300),
                "AWSLambda": ("fn-", 400), "AmazonCloudFront": ("E", 40), "AmazonDynamoDB": ("table-", 120),
                "AmazonEKS": ("cluster-", 12), "AWSDataTransfer": ("", 1)}
    regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]
    accounts = ["111111111111", "222222222222", "333333333333"]
    pool = []
    for svc, (pre, n) in services.items():
        for i in range(n):
            rid = f"{pre}{rnd.getrandbits(40):010x}" if pre else ""
            pool.append((rnd.choice(accounts), svc, rnd.choice(regions), rid, rnd.lognormvariate(-2.5, 1.6)))
    header = ["line_item_usage_account_id", "line_item_product_code", "product_region_code",
              "line_item_resource_id", "line_item_unblended_cost", "line_item_line_item_type",
              "line_item_usage_start_date", "line_item_usage_type"]
    total = 0.0
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "wt", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for k in range(rows):
            a, s, r, rid, scale = pool[rnd.randrange(len(pool))]
            cost = round(scale * rnd.random(), 8)
            total += cost
            w.writerow([a, s, r, rid, f"{cost:.8f}", "Usage", f"2026-09-{1 + k % 30:02d}T{k % 24:02d}:00:00Z", f"{s}-Usage"])
    print(f"{total:.6f}")

if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
