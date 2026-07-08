import sys
sys.path.append('/workspace/finance_app')
import database as db

def insert_repayments():
    # Mox Repayment
    mox_amount_hkd = 49507.70
    mox_amount_usdt = mox_amount_hkd / 7.8
    
    # Expense from USDT
    db.add_transaction('2026-07-08', mox_amount_usdt, 'USDT', 'Credit Card Repayment', 'expense', '还款 Mox Credit', 'Crypto Wallet')
    # Income to Mox (clearing the negative balance)
    db.add_transaction('2026-07-08', mox_amount_hkd, 'HKD', 'Credit Card Repayment', 'income', '还款 Mox Credit', 'Mox Credit')
    
    # DBS Repayment
    dbs_amount_hkd = 75852.00
    dbs_amount_usdt = dbs_amount_hkd / 7.8
    
    # Expense from USDT
    db.add_transaction('2026-07-08', dbs_amount_usdt, 'USDT', 'Credit Card Repayment', 'expense', '还款 DBS Credit Card', 'Crypto Wallet')
    # Income to DBS
    db.add_transaction('2026-07-08', dbs_amount_hkd, 'HKD', 'Credit Card Repayment', 'income', '还款 DBS Credit Card', 'DBS Credit Card')

    print("Repayments inserted successfully.")

if __name__ == '__main__':
    insert_repayments()
