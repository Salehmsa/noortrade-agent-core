"""
build_db.py — طبقة البيانات لوكيل NoorTrade
يحوّل noortrade_data.xlsx إلى قاعدة SQLite جاهزة للاستعلام.

لماذا SQLite ولماذا لا نترك الوكيل يقرأ Excel مباشرة؟
  1. SQL لغة يتقنها النموذج بامتياز — أفضل بكثير من توليد كود pandas
  2. القراءة فقط (read-only) = حدّ أمان طبيعي للوكيل
  3. ملف واحد بلا خادم، يعمل في أي مكان

التشغيل:  python build_db.py
"""

import sqlite3
from pathlib import Path
import pandas as pd

EXCEL_PATH = Path("noortrade_data.xlsx")
DB_PATH = Path("data/noortrade.db")


def build() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    xl = pd.ExcelFile(EXCEL_PATH)
    conn = sqlite3.connect(DB_PATH)

    for sheet in ["Orders", "Customers", "Products", "Returns"]:
        df = xl.parse(sheet)
        for col in df.columns:
            # التواريخ تُخزَّن كنص ISO — صيغة تفهمها دوال SQLite الزمنية
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].dt.strftime("%Y-%m-%d")
            # تنظيف المسافات الزائدة: "Riyadh " و "Riyadh" تُعاملان كمدينتين
            # مختلفتين في GROUP BY وتُفسد كل تقرير يبنيه الوكيل
            elif pd.api.types.is_string_dtype(df[col]):
                df[col] = df[col].str.strip()
        df.to_sql(sheet.lower(), conn, index=False)
        print(f"  {sheet.lower():12s} {len(df):>6,} صف")

    # فهارس على الأعمدة التي سيستعلم عنها الوكيل كثيراً
    cur = conn.cursor()
    for stmt in [
        "CREATE INDEX idx_orders_date ON orders(Order_Date)",
        "CREATE INDEX idx_orders_city ON orders(City)",
        "CREATE INDEX idx_orders_channel ON orders(Channel)",
        "CREATE INDEX idx_orders_product ON orders(Product_ID)",
        "CREATE INDEX idx_orders_customer ON orders(Customer_ID)",
        "CREATE INDEX idx_returns_order ON returns(Order_ID)",
    ]:
        cur.execute(stmt)

    # عرض جاهز يدمج الطلبات بالمنتجات والمرتجعات — يوفّر على الوكيل JOINات متكررة
    cur.execute("""
        CREATE VIEW v_sales AS
        SELECT
            o.Order_ID, o.Order_Date, o.Customer_ID, o.Product_ID,
            p.Product_Name, p.Category,
            o.Quantity, o.Unit_Price, o.Discount_Pct, o.Total_SAR,
            p.Unit_Cost,
            ROUND(o.Total_SAR - (p.Unit_Cost * o.Quantity), 2) AS Gross_Profit_SAR,
            o.Channel, o.City, o.Payment_Method,
            CASE WHEN r.Return_ID IS NOT NULL THEN 1 ELSE 0 END AS Is_Returned,
            r.Refund_Amount, r.Reason AS Return_Reason
        FROM orders o
        LEFT JOIN products p ON o.Product_ID = p.Product_ID
        LEFT JOIN returns  r ON o.Order_ID   = r.Order_ID
    """)

    conn.commit()
    conn.close()
    print(f"\n✓ تم البناء: {DB_PATH}  ({DB_PATH.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    build()
