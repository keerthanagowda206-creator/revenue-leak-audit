-- Revenue Leak Audit: database schema (SQLite)
-- Company: simulated Indian D2C e-commerce brand
-- Note: invoices.order_id is UNIQUE (one invoice per order), but payments and refunds
-- are intentionally NOT unique per invoice/order, because real leaks (duplicate refunds,
-- payment retries) show up exactly there.

CREATE TABLE customers (
    customer_id          TEXT PRIMARY KEY,
    customer_name        TEXT NOT NULL,
    city                 TEXT,
    state                TEXT,
    acquisition_channel  TEXT,   -- Instagram, Google Ads, Organic, Referral, Influencer
    signup_date          TEXT    -- YYYY-MM-DD
);

CREATE TABLE products (
    product_id    TEXT PRIMARY KEY,
    product_name  TEXT NOT NULL,
    category      TEXT NOT NULL,
    mrp           REAL NOT NULL,   -- list price
    cost_price    REAL NOT NULL
);

CREATE TABLE sales_reps (
    rep_id     TEXT PRIMARY KEY,
    rep_name   TEXT NOT NULL,
    region     TEXT,
    hire_date  TEXT
);

-- Approved discount limits per category (festival sales allow a higher cap)
CREATE TABLE discount_policy (
    category                   TEXT PRIMARY KEY,
    max_discount_pct           INTEGER NOT NULL,
    festival_max_discount_pct  INTEGER NOT NULL
);

CREATE TABLE orders (
    order_id        TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id),
    rep_id          TEXT REFERENCES sales_reps(rep_id),  -- only for rep-assisted (WhatsApp) orders
    channel         TEXT,    -- Website, App, Marketplace, WhatsApp
    order_date      TEXT NOT NULL,
    status          TEXT,    -- Delivered, Cancelled, Returned
    payment_method  TEXT,    -- UPI, Card, COD, NetBanking
    order_total     REAL NOT NULL
);

CREATE TABLE order_items (
    item_id       TEXT PRIMARY KEY,
    order_id      TEXT NOT NULL REFERENCES orders(order_id),
    product_id    TEXT NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL,
    unit_price    REAL NOT NULL,
    discount_pct  INTEGER NOT NULL,
    line_total    REAL NOT NULL
);

CREATE TABLE invoices (
    invoice_id      TEXT PRIMARY KEY,
    order_id        TEXT NOT NULL UNIQUE REFERENCES orders(order_id),
    invoice_date    TEXT NOT NULL,
    invoice_amount  REAL NOT NULL
);

CREATE TABLE payments (
    payment_id      TEXT PRIMARY KEY,
    invoice_id      TEXT NOT NULL REFERENCES invoices(invoice_id),
    payment_date    TEXT,
    amount          REAL NOT NULL,
    payment_status  TEXT     -- Success, Failed
);

CREATE TABLE refunds (
    refund_id      TEXT PRIMARY KEY,
    order_id       TEXT NOT NULL REFERENCES orders(order_id),
    refund_date    TEXT NOT NULL,
    refund_amount  REAL NOT NULL,
    reason         TEXT
);

CREATE INDEX idx_orders_customer  ON orders(customer_id);
CREATE INDEX idx_orders_date      ON orders(order_date);
CREATE INDEX idx_items_order      ON order_items(order_id);
CREATE INDEX idx_payments_invoice ON payments(invoice_id);
CREATE INDEX idx_refunds_order    ON refunds(order_id);
