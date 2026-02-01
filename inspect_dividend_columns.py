import pandas as pd
import numpy as np

df = pd.read_csv("stocks.csv", encoding="utf-8-sig", dtype=str)
# 숫자 컬럼 안전 변환
for c in ['연배당금_크롤링','연배당금_크롤링_auto']:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors='coerce')

# 비율 계산 (안전: 0 나누기 방지)
df['ratio_crawled_auto'] = df.apply(lambda r: (r['연배당금_크롤링'] / r['연배당금_크롤링_auto'])
                                    if pd.notna(r['연배당금_크롤링']) and pd.notna(r['연배당금_크롤링_auto']) and r['연배당금_크롤링_auto']!=0
                                    else np.nan, axis=1)

# 요약 통계
print("전체 행 수:", len(df))
print("ratio 통계:")
print(df['ratio_crawled_auto'].describe())

# 판별 기준별 개수
cond_monthly = df['ratio_crawled_auto'].between(10,14)   # auto가 월별로 보이는 경우
cond_annual = df['ratio_crawled_auto'].between(0.8,1.2)  # 둘 다 연환산으로 보이는 경우
cond_diff = df['ratio_crawled_auto'].between(0.2,5) & ~cond_annual  # 출처 차이 가능
print("auto가 월별(≈12)로 보이는 행:", cond_monthly.sum())
print("둘 다 연환산(≈1)로 보이는 행:", cond_annual.sum())
print("출처 차이 가능(둘 다 연환산이지만 값 차이):", cond_diff.sum())
print("불확실(나머지):", len(df) - (cond_monthly.sum()+cond_annual.sum()+cond_diff.sum()))
# 샘플 출력
print("\n월별로 의심되는 샘플(최대 10):")
print(df[cond_monthly].head(10)[['종목코드','종목명','연배당금_크롤링_auto','연배당금_크롤링','ratio_crawled_auto']])
