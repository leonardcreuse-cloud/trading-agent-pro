from datetime import datetime
from typing import Dict, List, Tuple

class DataValidation:
    """
    Data Validation & Quality Control
    - Validates data integrity from all sources
    - Detects anomalies, missing values, data type errors
    - Flags suspicious values
    - Source: Internal validation layer
    """
    
    def __init__(self):
        self.validation_rules = {
            'price': {'min': 0.01, 'max': 100000, 'type': float},
            'volume': {'min': 0, 'max': 10_000_000_000, 'type': int},
            'eps': {'min': -1000, 'max': 10000, 'type': float},
            'pe_ratio': {'min': 0, 'max': 1000, 'type': float},
            'market_cap': {'min': 0, 'max': 100_000_000_000_000, 'type': float},
            'revenue': {'min': 0, 'max': 10_000_000_000_000, 'type': float},
            'inflation': {'min': -5, 'max': 30, 'type': float},
            'unemployment': {'min': 0, 'max': 50, 'type': float},
            'fed_rate': {'min': 0, 'max': 20, 'type': float},
            'volatility': {'min': 0, 'max': 200, 'type': float}
        }
    
    def validate_price_data(self, ticker: str, price: float, date: str) -> Dict:
        """
        Validate single price point
        
        Returns: {valid, errors, warnings, timestamp}
        """
        
        errors = []
        warnings = []
        
        # Type check
        if not isinstance(price, (int, float)):
            errors.append(f'Price is not numeric: {type(price)}')
            return {
                'valid': False,
                'ticker': ticker,
                'errors': errors,
                'source': 'data_validation.py'
            }
        
        # Range check
        if price < 0.01:
            errors.append(f'Price below minimum: {price}')
        elif price > 100000:
            warnings.append(f'Price unusually high: {price}')
        
        # Date validation
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except:
            errors.append(f'Invalid date format: {date}')
        
        # Check for NaN/Inf
        if price != price:  # NaN check
            errors.append('Price is NaN')
        elif price == float('inf'):
            errors.append('Price is Infinity')
        
        return {
            'valid': len(errors) == 0,
            'ticker': ticker,
            'price': price,
            'date': date,
            'errors': errors,
            'warnings': warnings,
            'source': 'data_validation.py'
        }
    
    def validate_fundamental_data(self, ticker: str, metric_name: str, value: float) -> Dict:
        """
        Validate fundamental metric
        
        Returns: {valid, errors, data_quality_score}
        """
        
        errors = []
        data_quality_score = 100
        
        if value is None:
            errors.append(f'{metric_name} is None/null')
            data_quality_score = 0
        elif not isinstance(value, (int, float)):
            errors.append(f'{metric_name} is not numeric')
            data_quality_score = 0
        else:
            # Apply metric-specific rules
            if metric_name in self.validation_rules:
                rule = self.validation_rules[metric_name]
                
                if value < rule['min']:
                    errors.append(f'{metric_name} below minimum: {value} < {rule["min"]}')
                    data_quality_score -= 25
                
                if value > rule['max']:
                    errors.append(f'{metric_name} above maximum: {value} > {rule["max"]}')
                    data_quality_score -= 25
                
                # NaN/Inf check
                if value != value:
                    errors.append(f'{metric_name} is NaN')
                    data_quality_score = 0
                elif value == float('inf') or value == float('-inf'):
                    errors.append(f'{metric_name} is Infinity')
                    data_quality_score = 0
        
        return {
            'valid': len(errors) == 0,
            'ticker': ticker,
            'metric': metric_name,
            'value': value,
            'errors': errors,
            'data_quality_score': max(0, data_quality_score),
            'source': 'data_validation.py'
        }
    
    def detect_anomalies(self, ticker: str, historical_values: List[float], current_value: float) -> Dict:
        """
        Detect statistical anomalies using Z-score
        
        Returns: {anomaly_detected, z_score, severity}
        """
        
        if len(historical_values) < 2:
            return {
                'anomaly_detected': False,
                'reason': 'Insufficient historical data',
                'ticker': ticker
            }
        
        # Calculate mean and std dev
        mean = sum(historical_values) / len(historical_values)
        variance = sum((x - mean) ** 2 for x in historical_values) / len(historical_values)
        std_dev = variance ** 0.5
        
        if std_dev == 0:
            return {
                'anomaly_detected': False,
                'reason': 'Zero variance in historical data',
                'ticker': ticker
            }
        
        # Calculate Z-score
        z_score = (current_value - mean) / std_dev
        
        if abs(z_score) > 3:
            severity = 'CRITICAL'
            anomaly = True
        elif abs(z_score) > 2:
            severity = 'WARNING'
            anomaly = True
        else:
            severity = 'NORMAL'
            anomaly = False
        
        return {
            'anomaly_detected': anomaly,
            'ticker': ticker,
            'z_score': round(z_score, 2),
            'severity': severity,
            'mean': round(mean, 2),
            'std_dev': round(std_dev, 2),
            'current_value': current_value,
            'source': 'data_validation.py'
        }
    
    def check_data_freshness(self, source: str, last_update_date: str, max_age_days: int = 7) -> Dict:
        """
        Check if data is fresh enough
        
        Returns: {fresh, days_old, status}
        """
        
        try:
            last_update = datetime.strptime(last_update_date, '%Y-%m-%d')
            days_old = (datetime.now() - last_update).days
            
            if days_old > max_age_days:
                status = 'STALE'
                fresh = False
            else:
                status = 'CURRENT'
                fresh = True
            
            return {
                'fresh': fresh,
                'source': source,
                'days_old': days_old,
                'max_age_days': max_age_days,
                'status': status,
                'last_update': last_update_date
            }
        
        except Exception as e:
            return {
                'fresh': False,
                'error': str(e),
                'source': source
            }
    
    def generate_validation_report(self, ticker: str, validation_results: List[Dict]) -> Dict:
        """
        Generate comprehensive validation report
        
        Returns: {overall_valid, error_count, warning_count, data_quality_pct, issues}
        """
        
        if not validation_results:
            return {
                'overall_valid': True,
                'ticker': ticker,
                'error_count': 0,
                'warning_count': 0,
                'data_quality_pct': 100,
                'source': 'data_validation.py'
            }
        
        total_errors = 0
        total_warnings = 0
        quality_scores = []
        
        for result in validation_results:
            total_errors += len(result.get('errors', []))
            total_warnings += len(result.get('warnings', []))
            
            if 'data_quality_score' in result:
                quality_scores.append(result['data_quality_score'])
        
        # Calculate overall quality
        if quality_scores:
            avg_quality = sum(quality_scores) / len(quality_scores)
        else:
            avg_quality = 100 if total_errors == 0 else 0
        
        return {
            'overall_valid': total_errors == 0,
            'ticker': ticker,
            'error_count': total_errors,
            'warning_count': total_warnings,
            'data_quality_pct': round(avg_quality, 1),
            'validation_count': len(validation_results),
            'status': 'PASS' if total_errors == 0 else 'FAIL',
            'timestamp': datetime.now().isoformat(),
            'source': 'data_validation.py'
        }

if __name__ == "__main__":
    validator = DataValidation()
    
    print("\nData Validation Tests:")
    
    # Test price validation
    price_check = validator.validate_price_data('CRWD', 150.25, '2026-10-04')
    print(f"\nPrice validation: {price_check['valid']}")
    
    # Test fundamental validation
    eps_check = validator.validate_fundamental_data('CRWD', 'eps', 2.50)
    print(f"EPS validation: {eps_check['valid']}")
    
    # Test anomaly detection
    historical = [150, 151, 152, 153, 154, 155]
    anomaly = validator.detect_anomalies('CRWD', historical, 200)
    print(f"Anomaly detected: {anomaly['anomaly_detected']} (Z-score: {anomaly['z_score']})")
