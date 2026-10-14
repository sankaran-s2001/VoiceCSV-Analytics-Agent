"""Generate deterministic 1,000-row test dataset and verify known totals."""

import os
from pathlib import Path
import pandas as pd
import numpy as np

def generate_1000_dataset():
    fixture_dir = Path("tests/fixtures")
    fixture_dir.mkdir(parents=True, exist_ok=True)
    out_file = fixture_dir / "sample_1000.csv"

    np.random.seed(42)  # Deterministic seed
    n = 1000

    categories = ["Electronics", "Furniture", "Office Supplies", "Apparel"]
    regions = ["North America", "Europe", "Asia-Pacific", "Latin America"]
    statuses = ["Completed", "Returned", "Pending"]

    products_by_cat = {
        "Electronics": ["Laptop Pro", "Wireless Mouse", "Ultra HD Monitor", "Noise Cancelling Headphones"],
        "Furniture": ["Standing Desk", "Ergonomic Chair", "Bookshelf", "Filing Cabinet"],
        "Office Supplies": ["Whiteboard Marker", "Paper Ream", "Gel Pens Pack", "Stapler Set"],
        "Apparel": ["Branded Hoodie", "Cotton T-Shirt", "Executive Jacket", "Running Cap"]
    }

    base_prices = {
        "Laptop Pro": 1200.0,
        "Wireless Mouse": 25.0,
        "Ultra HD Monitor": 400.0,
        "Noise Cancelling Headphones": 150.0,
        "Standing Desk": 500.0,
        "Ergonomic Chair": 250.0,
        "Bookshelf": 120.0,
        "Filing Cabinet": 180.0,
        "Whiteboard Marker": 15.0,
        "Paper Ream": 20.0,
        "Gel Pens Pack": 10.0,
        "Stapler Set": 12.0,
        "Branded Hoodie": 60.0,
        "Cotton T-Shirt": 25.0,
        "Executive Jacket": 150.0,
        "Running Cap": 20.0
    }

    rows = []
    for i in range(1, n + 1):
        txn_id = f"TXN-{i:04d}"
        cust_num = (i % 80) + 1
        cust_id = f"CUST-{cust_num:03d}"
        cust_name = f"Customer_{cust_num}"
        cat = categories[i % len(categories)]
        prod_list = products_by_cat[cat]
        prod = prod_list[i % len(prod_list)]
        unit_price = base_prices[prod]
        quantity = ((i * 7) % 20) + 1
        sales = round(quantity * unit_price, 2)
        profit = round(sales * 0.30, 2)
        region = regions[i % len(regions)]
        status = statuses[i % len(statuses)]
        
        # 12 months spread in 2024
        month = (i % 12) + 1
        day = (i % 28) + 1
        date_str = f"2024-{month:02d}-{day:02d}"

        rows.append({
            "transaction_id": txn_id,
            "order_date": date_str,
            "customer_id": cust_id,
            "customer_name": cust_name,
            "region": region,
            "category": cat,
            "product_name": prod,
            "quantity": quantity,
            "unit_price": unit_price,
            "sales": sales,
            "profit": profit,
            "status": status
        })

    df = pd.DataFrame(rows)
    df.to_csv(out_file, index=False)
    print(f"Generated {len(df)} rows into {out_file}")
    print(f"Total Sales SUM: {df['sales'].sum():.2f}")
    print(f"Total Profit SUM: {df['profit'].sum():.2f}")
    print(f"Total Quantity SUM: {df['quantity'].sum()}")

if __name__ == "__main__":
    generate_1000_dataset()
