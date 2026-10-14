"""Create adversarial CSV test fixtures."""

from pathlib import Path

def create_adversarial_fixtures():
    fixtures_dir = Path("tests/fixtures")
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    # 1. UTF-8 with BOM
    bom_content = "\ufeffid,name,value\n1,Alpha,100\n2,Beta,200\n"
    with open(fixtures_dir / "adversarial_bom.csv", "w", encoding="utf-8-sig") as f:
        f.write(bom_content)

    # 2. Windows-1252 with European accents (Café, München, Crème)
    cp1252_content = "id,city,item,price\n1,München,Café,3.50\n2,Zürich,Crème Brûlée,6.00\n"
    with open(fixtures_dir / "adversarial_cp1252.csv", "w", encoding="cp1252") as f:
        f.write(cp1252_content)

    # 3. Duplicate and messy headers
    dup_content = "Sales,Sales,Sales!,123Price,  Customer Name  ,,Profit %\n10,20,30,40,Alice,X,5.5\n50,60,70,80,Bob,Y,8.0\n"
    with open(fixtures_dir / "adversarial_duplicate_headers.csv", "w", encoding="utf-8") as f:
        f.write(dup_content)

    # 4. Text identifiers with leading zeros
    leading_zeros_content = "account_code,zip_code,amount\n00105,02134,150.00\n00208,01002,280.50\n00034,08540,99.99\n"
    with open(fixtures_dir / "adversarial_leading_zeros.csv", "w", encoding="utf-8") as f:
        f.write(leading_zeros_content)

    # 5. Nulls, NaNs, infinities, and blanks
    nulls_content = "id,val1,val2,val3\n1,10.5,NaN,text\n2,,inf,\n3,-inf,50.0,None\n4,NULL,null, \n"
    with open(fixtures_dir / "adversarial_nulls.csv", "w", encoding="utf-8") as f:
        f.write(nulls_content)

    # 6. Formula injection strings
    formula_content = "id,user_input,score\n1,=CMD('calc.exe'),10\n2,+SUM(A1:A10),20\n3,-2+3*4,30\n4,@SUM(B1:B2),40\n"
    with open(fixtures_dir / "adversarial_formula_injection.csv", "w", encoding="utf-8") as f:
        f.write(formula_content)

    # 7. Malformed rows (inconsistent row length)
    malformed_content = "col1,col2,col3\n1,2,3\n4,5\n6,7,8,9,10\n"
    with open(fixtures_dir / "adversarial_malformed.csv", "w", encoding="utf-8") as f:
        f.write(malformed_content)

    print("Created all adversarial fixtures in tests/fixtures/")

if __name__ == "__main__":
    create_adversarial_fixtures()
