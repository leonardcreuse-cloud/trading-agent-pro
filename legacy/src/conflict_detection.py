import sqlite3
from datetime import datetime
from typing import Dict, List, Tuple

class ConflictDetection:
    """
    Data Conflict Detection & Resolution
    - Identifies contradictions between data sources
    - Flags unreliable sources
    - Marks data with conflict status
    
    Conflict levels:
    - CRITICAL: >20% variance between sources
    - WARNING: 10-20% variance
    - MINOR: <10% variance
    """
    
    def __init__(self, db_path='../data/trading_pro.db'):
        self.db_path = db_path
    
    def detect_price_conflict(self, ticker: str, price_data: Dict) -> Dict:
        """
        Detect price conflicts between Yahoo Finance and external sources
        
        price_data: {
            'yahoo': 150.25,
            'sec_filing': 150.50,
            'source_dates': {'yahoo': '2026-10-04', 'sec_filing': '2026-10-04'}
        }
        
        Returns: {conflict_detected, variance_pct, sources_affected, resolution}
        """
        
        prices = {k: v for k, v in price_data.items() if k not in ['source_dates', 'ticker']}
        
        if len(prices) < 2:
            return {
                'ticker': ticker,
                'conflict_detected': False,
                'reason': 'Insufficient sources',
                'source': 'conflict_detection.py'
            }
        
        max_price = max(prices.values())
        min_price = min(prices.values())
        variance_pct = ((max_price - min_price) / min_price) * 100
        
        if variance_pct > 20:
            severity = 'CRITICAL'
        elif variance_pct > 10:
            severity = 'WARNING'
        else:
            severity = 'MINOR'
        
        return {
            'ticker': ticker,
            'conflict_detected': variance_pct > 10,
            'variance_pct': round(variance_pct, 2),
            'severity': severity,
            'max_price': max_price,
            'min_price': min_price,
            'sources_affected': list(prices.keys()),
            'recommended_source': 'SEC_FILING' if variance_pct > 10 else 'YAHOO',
            'timestamp': datetime.now().isoformat()
        }
    
    def detect_fundamental_conflict(self, ticker: str, metric_name: str, values: Dict[str, float]) -> Dict:
        """
        Detect conflicts in fundamental metrics (EPS, Revenue, etc)
        
        values: {
            'SEC_10K': 2.50,
            'Yahoo': 2.48,
            'Yahoo_2': 2.45
        }
        
        Returns: {conflict_detected, variance, outliers, recommended_value}
        """
        
        if len(values) < 2:
            return {
                'metric': metric_name,
                'conflict_detected': False,
                'reason': 'Insufficient sources'
            }
        
        value_list = list(values.values())
        mean_val = sum(value_list) / len(value_list)
        max_val = max(value_list)
        min_val = min(value_list)
        
        variance_pct = ((max_val - min_val) / abs(mean_val)) * 100 if mean_val != 0 else 0
        
        outliers = []
        for source, val in values.items():
            if abs(val - mean_val) / abs(mean_val) * 100 > 15:
                outliers.append({
                    'source': source,
                    'value': val,
                    'deviation_from_mean': round(abs(val - mean_val) / abs(mean_val) * 100, 2)
                })
        
        if variance_pct > 20:
            severity = 'CRITICAL'
            recommended_source = 'SEC' if 'SEC' in values else max(values, key=values.get)
        elif variance_pct > 10:
            severity = 'WARNING'
            recommended_source = 'SEC' if 'SEC' in values else None
        else:
            severity = 'MINOR'
            recommended_source = None
        
        return {
            'ticker': ticker,
            'metric': metric_name,
            'conflict_detected': variance_pct > 10,
            'variance_pct': round(variance_pct, 2),
            'severity': severity,
            'mean_value': round(mean_val, 3),
            'range': f"{min_val} - {max_val}",
            'outliers': outliers,
            'recommended_source': recommended_source,
            'source_count': len(values)
        }
    
    def detect_date_staleness(self, ticker: str, metric_name: str, source_dates: Dict[str, str]) -> Dict:
        """
        Detect if data is stale across sources
        
        source_dates: {
            'SEC_10K': '2026-09-30',
            'Yahoo': '2026-10-04'
        }
        
        Returns: {staleness_detected, most_recent, most_stale, days_difference}
        """
        
        if not source_dates:
            return {'staleness_detected': False}
        
        dates = {}
        for source, date_str in source_dates.items():
            try:
                dates[source] = datetime.strptime(date_str, '%Y-%m-%d')
            except:
                pass
        
        if len(dates) < 2:
            return {
                'metric': metric_name,
                'staleness_detected': False,
                'reason': 'Insufficient dated sources'
            }
        
        most_recent = max(dates.values())
        most_stale = min(dates.values())
        days_diff = (most_recent - most_stale).days
        
        if days_diff > 90:
            severity = 'CRITICAL'
        elif days_diff > 30:
            severity = 'WARNING'
        else:
            severity = 'MINOR'
        
        return {
            'ticker': ticker,
            'metric': metric_name,
            'staleness_detected': days_diff > 30,
            'severity': severity,
            'most_recent': most_recent.strftime('%Y-%m-%d'),
            'most_stale': most_stale.strftime('%Y-%m-%d'),
            'days_difference': days_diff,
            'sources': list(dates.keys())
        }
    
    def generate_conflict_report(self, ticker: str, all_conflicts: List[Dict]) -> Dict:
        """
        Generate summary conflict report
        
        Returns: {ticker, total_conflicts, critical_count, warning_count, data_reliability_pct}
        """
        
        if not all_conflicts:
            return {
                'ticker': ticker,
                'total_conflicts': 0,
                'critical_count': 0,
                'warning_count': 0,
                'data_reliability_pct': 100,
                'status': 'CLEAN'
            }
        
        critical = len([c for c in all_conflicts if c.get('severity') == 'CRITICAL'])
        warning = len([c for c in all_conflicts if c.get('severity') == 'WARNING'])
        
        reliability = max(0, 100 - (critical * 10) - (warning * 5))
        
        return {
            'ticker': ticker,
            'total_conflicts': len(all_conflicts),
            'critical_count': critical,
            'warning_count': warning,
            'data_reliability_pct': reliability,
            'status': 'ISSUES_FOUND' if critical > 0 else 'ACCEPTABLE',
            'timestamp': datetime.now().isoformat()
        }

if __name__ == "__main__":
    cd = ConflictDetection()
    
    # Test price conflict
    test_price = {
        'yahoo': 150.25,
        'sec_filing': 150.50,
        'source_dates': {'yahoo': '2026-10-04', 'sec_filing': '2026-10-04'}
    }
    
    # Test fundamental conflict
    test_eps = {
        'SEC_10K': 2.50,
        'Yahoo': 2.48,
        'MarketWatch': 2.45
    }
    
    for ticker in ['CRWD', 'NET', 'RKLB', 'MP']:
        print(f"\n{ticker} - Conflict Detection:")
        
        price_check = cd.detect_price_conflict(ticker, test_price)
        print(f"  Price Conflict: {price_check.get('conflict_detected')}")
        
        eps_check = cd.detect_fundamental_conflict(ticker, 'EPS', test_eps)
        print(f"  EPS Variance: {eps_check.get('variance_pct')}%")
