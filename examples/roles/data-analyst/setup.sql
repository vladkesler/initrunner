-- Sample database for the data-analyst role.
-- Usage: sqlite3 sample.db < setup.sql

CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    email       TEXT    NOT NULL,
    region      TEXT    NOT NULL,
    joined_date TEXT    NOT NULL  -- ISO 8601 date
);

CREATE TABLE IF NOT EXISTS products (
    id       INTEGER PRIMARY KEY,
    name     TEXT    NOT NULL,
    category TEXT    NOT NULL,
    price    REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS sales (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL,
    total       REAL    NOT NULL,
    sale_date   TEXT    NOT NULL  -- ISO 8601 date
);

-- Customers
INSERT INTO customers (id, name, email, region, joined_date) VALUES
(1, 'Alice Chen',     'alice@example.com',   'North America', '2023-01-15'),
(2, 'Bob Martinez',   'bob@example.com',     'Europe',        '2023-03-22'),
(3, 'Carol Tanaka',   'carol@example.com',   'Asia Pacific',  '2023-02-10'),
(4, 'Dave Johnson',   'dave@example.com',    'North America', '2023-06-01'),
(5, 'Eve Schmidt',    'eve@example.com',     'Europe',        '2023-04-18'),
(6, 'Frank Okafor',   'frank@example.com',   'Africa',        '2023-07-30'),
(7, 'Grace Li',       'grace@example.com',   'Asia Pacific',  '2023-05-12'),
(8, 'Hank Wilson',    'hank@example.com',    'North America', '2023-08-25');

-- Products
INSERT INTO products (id, name, category, price) VALUES
(1, 'Widget Pro',       'Hardware',  29.99),
(2, 'Widget Basic',     'Hardware',  14.99),
(3, 'Cloud Starter',    'Software',  9.99),
(4, 'Cloud Enterprise', 'Software',  49.99),
(5, 'Support Plan',     'Services',  19.99),
(6, 'Training Bundle',  'Services',  99.99);

-- Sales (Q1-Q4 2024)
INSERT INTO sales (id, customer_id, product_id, quantity, total, sale_date) VALUES
(1,  1, 1, 3,  89.97,  '2024-01-10'),
(2,  2, 3, 1,   9.99,  '2024-01-15'),
(3,  3, 4, 2,  99.98,  '2024-01-22'),
(4,  1, 5, 1,  19.99,  '2024-02-05'),
(5,  4, 2, 5,  74.95,  '2024-02-14'),
(6,  5, 6, 1,  99.99,  '2024-02-28'),
(7,  6, 1, 2,  59.98,  '2024-03-10'),
(8,  7, 3, 3,  29.97,  '2024-03-18'),
(9,  2, 4, 1,  49.99,  '2024-04-02'),
(10, 8, 2, 4,  59.96,  '2024-04-15'),
(11, 1, 6, 1,  99.99,  '2024-05-01'),
(12, 3, 5, 2,  39.98,  '2024-05-20'),
(13, 5, 1, 1,  29.99,  '2024-06-08'),
(14, 4, 3, 2,  19.98,  '2024-06-22'),
(15, 7, 4, 1,  49.99,  '2024-07-05'),
(16, 6, 2, 3,  44.97,  '2024-07-19'),
(17, 8, 5, 1,  19.99,  '2024-08-03'),
(18, 1, 4, 1,  49.99,  '2024-08-18'),
(19, 2, 1, 2,  59.98,  '2024-09-01'),
(20, 3, 6, 1,  99.99,  '2024-09-15'),
(21, 4, 5, 3,  59.97,  '2024-10-02'),
(22, 5, 3, 1,   9.99,  '2024-10-20'),
(23, 7, 1, 2,  59.98,  '2024-11-05'),
(24, 6, 4, 1,  49.99,  '2024-11-22'),
(25, 8, 6, 1,  99.99,  '2024-12-10');
