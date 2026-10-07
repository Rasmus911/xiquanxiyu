export interface Employee {
  id: string
  username: string
  display_name: string
  role: 'male_scrubber' | 'female_scrubber' | 'floor_attendant' | 'cashier' | 'inventory' | 'manager' | 'admin'
  is_active: boolean
  mobile_full_access?: boolean
  allowed_channels?: Array<'desktop' | 'web' | 'mobile'>
  protected_account?: boolean
  deleted_at?: string | null
}

export interface Terminal {
  id: string
  code: string
  name: string
  mobile_scope: 'frontdesk' | 'scrub' | 'rest' | 'both'
  printer_name?: string
  is_active: boolean
}

export interface Wristband {
  id: string
  number: string
  is_active?: boolean
  bath_area?: 'male' | 'female' | 'other'
  status: 'available' | 'in_use' | 'lost' | 'disabled'
  note?: string
  visit_id?: string
  opened_at?: string
  amount: string
  party_id?: string
  linked_numbers?: string[]
  linked_visit_ids?: string[]
  linked_total_amount?: string
  version: number
}

export interface CatalogItem {
  id: string
  kind: 'ticket' | 'service' | 'product' | 'compensation' | 'package'
  category: string
  name: string
  mobile_scope?: 'frontdesk' | 'scrub' | 'rest' | 'both'
  reference_code?: string | null
  package_definition?: {schema:number;display_contents:string[];slots:Array<{catalog_item_ids:string[];quantity:string}>} | null
  price: string
  is_active: boolean
  stock_tracked: boolean
  stock_quantity: string
  low_stock_threshold: string
  sort_order: number
  can_edit?: boolean
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
  unit_cost: string | null
  is_active: boolean
  version: number
  legacy_catalog_item_id: string | null
}
export type Consumable = Pick<StockItem, 'id' | 'name' | 'category' | 'base_unit' | 'package_spec' | 'stock_quantity' | 'version'>
export interface ManualConsumption { stock_item_id: string; quantity: string }
export interface StockUsage {
  catalog_item_id: string; catalog_name: string; stock_item_id: string; stock_name: string
  base_unit: string; usage_count: number; total_quantity: string; is_most_used: boolean
}
export interface StockMovement {
  id: string; stock_item_id: string; movement_type: string; quantity: string; balance_after: string
  input_quantity: string; input_unit: string; conversion_factor: string; reason: string; created_at: string
  base_unit: string; package_unit: string; balance_before: string
  cost?: { id:string; version:number; unit_cost:string; total_cost:string; base_unit_cost:string; operator_id:string; created_at:string } | null
}

export interface OrderItem {
  id: string
  catalog_item_id?: string | null
  kind: string
  name: string
  unit_price: string
  quantity: string
  covered_quantity?: string
  included_amount?: string
  package_order_item_id?: string | null
  total_amount: string
  status: string
  void_reason?: string
  inventory_mode?: 'manual' | 'legacy'
  inventory_consumption?: Array<ManualConsumption & { name: string; base_unit: string }>
}

export interface Visit {
  id: string
  version: number
  wristband_id: string
  wristband_number: string
  member_id?: string
  party_id?: string
  status: string
  opened_at: string
  total_amount: string
  items: OrderItem[]
  linked_visits?: Visit[]
  linked_total_amount?: string
}

export interface Member {
  id: string
  phone: string
  name?: string
  balance: string
  is_active: boolean
  note?: string
  has_stored_value?: boolean
  has_pass?: boolean
  active_pass_count?: number
  pass_remaining?: number
  pass_total?: number
  ledgers?: Array<Record<string, string>>
  passes?: Array<Record<string, string | number | boolean>>
}
