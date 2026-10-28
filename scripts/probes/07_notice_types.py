import io,sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import akshare as ak
df = ak.stock_individual_notice_report(security="600519")
print("rows:", len(df))
print("=== TYPE DISTRIBUTION ===")
print(df["公告类型"].value_counts().to_string())
print("=== LATEST 5 ===")
print(df.head(5)[["公告日期","公告类型","公告标题"]].to_string())
