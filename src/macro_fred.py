#!/usr/bin/env python3
"""
FRED Parser - PRODUCTION VERSION using pandas-datareader
Direct official data from Federal Reserve Economic Data
"""

import pandas as pd
from datetime import datetime, timedelta
import sqlite3
import sys

class MacroFRED:
    """Production FRED parser using pandas-datareader"""
    
    INDICATORS = {
        'CPI': 'CPIAUCSL',              # Consumer Price Index
        'UNEMPLOYMENT': 'UNRATE',        # Unemployment Rate
        'FED_RATE': 'FEDFUNDS',         # Federal Funds Rate
        'T10Y2Y': 'T10Y2Y',             # 10Y-2Y Yield Curve
        'VIX': 'VIXCLS'                 # VIX Volatility
    }
    
    def __init__(self):
        self.init_db()
    
    def init_db(self):
        """Initialize SQLite"""
        conn = sqlite3.connect('data/trading_pro.db')
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS macro_data (
            indicator TEXT,
            value REAL,
            date TEXT,
            source TEXT,
            confidence INTEGER,
            timestamp TEXT,
            PRIMARY KEY (indicator, date)
        )''')
        
        conn.commit()
        conn.close()
    
    def fetch_fred_indicator(self, indicator_name, series_id):
        """Fetch indicator from FRED"""
        try:
            print(f"  [FRED] Fetching {indicator_name} ({series_id})...")
            
            from pandas_datareader import data as web
            
            # Fetch last 5 years
            start = datetime.now() - timedelta(days=365*5)
            data = web.DataReader(series_id, 'fred', start=start)
            
            if data.empty:
                print(f"  ❌ {indicator_name}: No data")
                return None
            
            # Get latest value
            latest = data.iloc[-1]
            latest_date = data.index[-1].strftime('%Y-%m-%d')
            latest_value = float(latest[series_id])
            
            return {
                'value': latest_value,
                'date': latest_date,
                'name': indicator_name
            }
        
        except Exception as e:
            print(f"  ❌ {indicator_name}: {str(e)}")
            return None
    
    def save_to_db(self, indicator, value, date):
        """Save to SQLite"""
        try:
            conn = sqlite3.connect('data/trading_pro.db')
            c = conn.cursor()
            
            c.execute('''INSERT OR REPLACE INTO macro_data 
                (indicator, value, date, source, confidence, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)''',
                (indicator, value, date, 'FRED', 99, datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"  [DB Error] {str(e)}")
            return False
    
    def interpret_data(self, indicator, value):
        """Interpret macro indicators"""
        interpretations = {
            'CPI': lambda v: "✓ Normal" if 2 < v < 4 else ("⚠️ High inflation" if v >= 4 else "✓ Low"),
            'UNEMPLOYMENT': lambda v: "✓ Good" if v < 4.5 else ("⚠️ Rising" if v > 5.5 else "⚠️ Moderate"),
            'FED_RATE': lambda v: f"Current rate: {v:.2f}%",
            'T10Y2Y': lambda v: "⚠️ INVERTED" if v < 0 else ("⚠️ FLAT" if v < 0.5 else "✓ NORMAL"),
            'VIX': lambda v: "✓ Low volatility" if v < 15 else ("⚠️ Moderate" if v < 25 else "🔴 High fear")
        }
        
        if indicator in interpretations:
            return interpretations[indicator](value)
        return ""
    
    def run(self):
        """Full macro analysis from Federal Reserve"""
        print("\n[MACRO ANALYSIS - FEDERAL RESERVE OFFICIAL DATA]")
        print("=" * 75)
        
        results = {}
        
        for indicator_name, series_id in self.INDICATORS.items():
            data = self.fetch_fred_indicator(indicator_name, series_id)
            
            if data:
                value = data['value']
                date = data['date']
                
                # Save to DB
                self.save_to_db(indicator_name, value, date)
                
                # Interpret
                interpretation = self.interpret_data(indicator_name, value)
                
                # Display
                print(f"  ✓ {indicator_name:20} {value:8.2f} ({date}) {interpretation}")
                results[indicator_name] = value
            else:
                results[indicator_name] = None
        
        print("\n" + "=" * 75)
        print("✅ MACRO DATA SUMMARY (OFFICIAL FEDERAL RESERVE):")
        
        if results['CPI']:
            print(f"   CPI Inflation:          {results['CPI']:.2f}%")
        if results['UNEMPLOYMENT']:
            print(f"   Unemployment Rate:      {results['UNEMPLOYMENT']:.2f}%")
        if results['FED_RATE']:
            print(f"   Federal Funds Rate:     {results['FED_RATE']:.2f}%")
        if results['T10Y2Y']:
            print(f"   Yield Curve (10Y-2Y):   {results['T10Y2Y']:.2f}%")
        if results['VIX']:
            print(f"   VIX Volatility Index:   {results['VIX']:.2f}")
        
        print("=" * 75)
        
        return {
            'cpi_inflation': results['CPI'],
            'unemployment_rate': results['UNEMPLOYMENT'],
            'federal_funds_rate': results['FED_RATE'],
            'yield_curve_10y2y': results['T10Y2Y'],
            'vix_volatility': results['VIX'],
            'source': 'FRED (Federal Reserve)',
            'confidence': 99,
            'timestamp': datetime.now().isoformat()
        }


if __name__ == "__main__":
    macro = MacroFRED()
    macro.run()