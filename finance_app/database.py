import sqlite3
import pandas as pd
from datetime import datetime
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'finance.db')

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create transactions table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        amount REAL NOT NULL,
        category TEXT,
        type TEXT NOT NULL, -- 'income' or 'expense'
        description TEXT,
        source TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Create budgets table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS budgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month TEXT NOT NULL UNIQUE, -- Format: YYYY-MM
        income_budget REAL NOT NULL DEFAULT 0,
        expense_budget REAL NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()

def add_transaction(date, amount, category, t_type, description, source):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO transactions (date, amount, category, type, description, source)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (date, amount, category, t_type, description, source))
    conn.commit()
    conn.close()

def set_budget(month, income_budget, expense_budget):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO budgets (month, income_budget, expense_budget)
    VALUES (?, ?, ?)
    ON CONFLICT(month) DO UPDATE SET
        income_budget=excluded.income_budget,
        expense_budget=excluded.expense_budget
    ''', (month, income_budget, expense_budget))
    conn.commit()
    conn.close()

def get_budget(month):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT income_budget, expense_budget FROM budgets WHERE month = ?', (month,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {'income_budget': result[0], 'expense_budget': result[1]}
    return {'income_budget': 0, 'expense_budget': 0}

def get_transactions_by_month(month):
    """month format: YYYY-MM"""
    conn = get_connection()
    query = "SELECT * FROM transactions WHERE date LIKE ?"
    df = pd.read_sql_query(query, conn, params=(f"{month}%",))
    conn.close()
    return df

def get_all_transactions():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM transactions ORDER BY date DESC", conn)
    conn.close()
    return df

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
