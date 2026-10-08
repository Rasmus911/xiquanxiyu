export type MobileRole = 'admin' | 'male_scrubber' | 'female_scrubber' | 'floor_attendant' | 'inventory'

export interface MobileEmployee {
  id: string
  username: string
  display_name: string
  role: MobileRole
  role_label: string
  capabilities?: {
    registration_token_view?: boolean
    orders_view?: boolean
    order_all?: boolean
    catalog_all?: boolean
    reports_view?: boolean
    inventory_manage?: boolean
    reports?: boolean
    inventory_add?: boolean
  }
}

export interface MobileWristband {
  number: string
  bath_area: 'male' | 'female'
  visit_id: string
  version?: number
  opened_at: string
  amount: string
  package_catalog_item_id?: string | null
}

export interface MobileCatalogItem {
  id: string
  kind: 'service' | 'product' | 'package'
  package_definition?: {schema:number;display_contents:string[];slots:Array<{catalog_item_ids:string[];quantity:string}>} | null
  category: string
  name: string
  mobile_scope: 'frontdesk' | 'scrub' | 'rest' | 'both'
  price: string
  stock_tracked: boolean
  stock_quantity: string
  low_stock_threshold: string
  sort_order: number
  is_active?: boolean
  can_edit?: boolean
  version?: number
}

export interface StockItem {
  id: string
  name: string
  category: string
  base_unit: string
  package_unit: string
  units_per_package: string
  package_spec: string
  stock_quantity: string
  low_stock_threshold: string
  is_active: boolean
  version: number
  unit_cost?: string | null
}
export type Consumable = Pick<StockItem, 'id' | 'name' | 'category' | 'base_unit' | 'package_spec' | 'stock_quantity' | 'version'>
export interface Consumption { stock_item_id: string; quantity: string }
export interface StockUsage {
  catalog_item_id: string; catalog_name: string; stock_item_id: string; stock_name: string
  base_unit: string; usage_count: number; total_quantity: string; is_most_used: boolean
}

export interface MobileBootstrap {
  employee: MobileEmployee
  wristbands: MobileWristband[]
  catalog: MobileCatalogItem[]
}

export interface MobileReportSummary {
  settlement_count: number
  operating_revenue: string
  member_recharge: string
  stored_value_recharge?: string
  pass_card_sales?: string
  actual_cash_inflow: string
  stored_value_consumed: string
  cashflow_totals: Record<string, string>
}

export interface MobileReportItem {
  kind: string
  name: string
  quantity: string
  amount: string
}

export interface MobileTrendPoint {
  date: string
  revenue: string
  recharge: string
  cash_inflow: string
  settlement_count: number
}

export interface MobileManagementReport {
  summary: MobileReportSummary
  items: MobileReportItem[]
  trend: MobileTrendPoint[]
  insights?: {
    previous: MobileReportSummary
    visit_count: number
    average_visit_revenue: string | null
    member_visit_count: number
    member_visit_share: number | null
    hours: Array<{hour:number;visits:number;gross_amount:string}>
    purchase_cost: {recorded_amount:string;unpriced_receipts:number;receipt_count:number}
  }
}

export interface DownloadConfig {
  version: string
  versionCode: number
  minimumVersionCode: number
  androidApkUrl: string
  sha256: string
  releaseNotes: string
}
