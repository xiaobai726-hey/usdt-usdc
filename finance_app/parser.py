import pandas as pd
import numpy as np

def process_statement(df, date_col, amount_col, desc_col, type_col=None, income_val=None, expense_val=None, date_format=None, invert_amount=False):
    """
    Process an uploaded bank statement dataframe into a standardized format.
    """
    try:
        # Create a copy to avoid SettingWithCopyWarning
        processed_df = df.copy()
        
        # Parse dates
        if date_format:
            processed_df['date'] = pd.to_datetime(processed_df[date_col], format=date_format).dt.strftime('%Y-%m-%d')
        else:
            processed_df['date'] = pd.to_datetime(processed_df[date_col]).dt.strftime('%Y-%m-%d')
            
        # Parse amounts
        # Remove commas and convert to float
        processed_df['amount'] = processed_df[amount_col].astype(str).str.replace(',', '').astype(float)
        
        # Determine type (income or expense)
        if type_col and income_val and expense_val:
            processed_df['type'] = np.where(processed_df[type_col] == income_val, 'income', 'expense')
        else:
            # If no type column, assume positive is income, negative is expense (or vice versa if invert_amount is True)
            if invert_amount:
                processed_df['type'] = np.where(processed_df['amount'] < 0, 'income', 'expense')
                processed_df['amount'] = processed_df['amount'].abs()
            else:
                processed_df['type'] = np.where(processed_df['amount'] > 0, 'income', 'expense')
                processed_df['amount'] = processed_df['amount'].abs()
                
        # Descriptions
        processed_df['description'] = processed_df[desc_col].astype(str)
        
        # Default category
        processed_df['category'] = 'Uncategorized'
        
        # Select only needed columns
        result_df = processed_df[['date', 'amount', 'category', 'type', 'description']]
        return result_df, None
    except Exception as e:
        return None, str(e)
