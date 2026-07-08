import pandas as pd
import numpy as np
import pdfplumber
import pytesseract
from PIL import Image
import io
import re

def process_csv_statement(df, date_col, amount_col, desc_col, type_col=None, income_val=None, expense_val=None, date_format=None, invert_amount=False):
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

def extract_text_from_pdf(file_bytes):
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text
    except Exception as e:
        return f"Error reading PDF: {str(e)}"

def extract_text_from_image(file_bytes):
    try:
        image = Image.open(io.BytesIO(file_bytes))
        # Use English, Simplified Chinese, and Traditional Chinese
        text = pytesseract.image_to_string(image, lang='eng+chi_sim+chi_tra')
        return text
    except Exception as e:
        return f"Error reading Image: {str(e)}"

def parse_raw_text_to_df(text):
    """
    Attempt to extract transactions from raw text using regex.
    Looks for patterns like: YYYY-MM-DD ... Amount ... Description
    This is a basic heuristic parser and might need adjustment based on actual statement formats.
    """
    lines = text.split('\n')
    transactions = []
    
    # Regex to find dates like 2026-01-01, 2026/01/01, 01/01/2026, etc.
    date_pattern = re.compile(r'(\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})')
    # Regex to find amounts like 1,234.56 or -123.45
    amount_pattern = re.compile(r'[-+]?\s*\d{1,3}(?:,\d{3})*\.\d{2}')
    
    for line in lines:
        date_match = date_pattern.search(line)
        if date_match:
            amounts = amount_pattern.findall(line)
            if amounts:
                # Take the last amount found on the line as the transaction amount (often balance is also there)
                amount_str = amounts[-1].replace(',', '').replace(' ', '')
                amount = float(amount_str)
                
                # Remove date and amount from line to get description
                desc = line.replace(date_match.group(1), '').replace(amounts[-1], '').strip()
                
                # Standardize date
                try:
                    date_obj = pd.to_datetime(date_match.group(1))
                    date_str = date_obj.strftime('%Y-%m-%d')
                except:
                    continue
                    
                t_type = 'income' if amount > 0 else 'expense'
                
                transactions.append({
                    'date': date_str,
                    'amount': abs(amount),
                    'category': 'Uncategorized',
                    'type': t_type,
                    'description': desc if desc else 'Parsed from text'
                })
                
    if transactions:
        return pd.DataFrame(transactions), None
    else:
        return None, "No transactions could be automatically parsed from the text. The format might not be supported."

