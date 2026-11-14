// Reports: figures over the orders, the stock and the shipments, and their CSV.

export type {
  Cohort,
  CustomerSales,
  DailySales,
  ProductSales,
  PromotionUsage,
  SalesSummary,
  ShippingCosts,
  StockValue,
  WeekdaySales,
} from './domain/report.ts'
export { dailySalesCsv, promotionUsageCsv, stockValuesCsv, toCsv } from './adapters/csv.ts'
export type {
  MonthlyMargin,
  MonthlySales,
  ReorderLine,
  ReportsDeps,
  StockValuation,
} from './services/reports.ts'
export { Reports } from './services/reports.ts'
