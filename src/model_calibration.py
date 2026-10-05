import numpy as np
from datetime import datetime
from typing import Dict, List

class ModelCalibration:
    """
    Model Calibration & Parameter Optimization
    - Tunes signal thresholds based on backtest results
    - Optimizes holding period
    - Calibrates risk parameters
    - Source: Backtest results
    """
    
    def __init__(self):
        self.default_signal_threshold = 60
        self.default_holding_days = 5
    
    def optimize_signal_threshold(self,
                                 backtest_results_by_threshold: Dict[float, Dict]) -> Dict:
        """
        Find optimal signal threshold based on backtest performance
        
        backtest_results_by_threshold: {
            55: {win_rate: 52, sharpe: 0.95, max_dd: 25},
            60: {win_rate: 65, sharpe: 1.20, max_dd: 18},
            65: {win_rate: 72, sharpe: 1.10, max_dd: 15},
            70: {win_rate: 68, sharpe: 0.85, max_dd: 12}
        }
        
        Returns: {optimal_threshold, performance_score, recommended_threshold}
        """
        
        if not backtest_results_by_threshold:
            return {'optimal_threshold': self.default_signal_threshold}
        
        best_threshold = None
        best_score = -np.inf
        threshold_scores = {}
        
        for threshold, results in backtest_results_by_threshold.items():
            # Composite score: win_rate + sharpe - max_dd penalty
            score = (
                results.get('win_rate', 50) * 0.40 +
                results.get('sharpe_ratio', 0) * 30 +
                max(0, 20 - results.get('max_drawdown_pct', 20)) * 0.5
            )
            
            threshold_scores[threshold] = score
            
            if score > best_score:
                best_score = score
                best_threshold = threshold
        
        return {
            'optimal_threshold': best_threshold,
            'optimization_score': round(best_score, 2),
            'all_thresholds': threshold_scores,
            'recommended_threshold': best_threshold,
            'source': 'model_calibration.py'
        }
    
    def optimize_holding_period(self,
                               backtest_results_by_holding: Dict[int, Dict]) -> Dict:
        """
        Find optimal holding period (days)
        
        backtest_results_by_holding: {
            3: {win_rate: 58, sharpe: 0.95},
            5: {win_rate: 65, sharpe: 1.20},
            10: {win_rate: 62, sharpe: 1.05},
            20: {win_rate: 55, sharpe: 0.85}
        }
        
        Returns: {optimal_holding_days, performance_score}
        """
        
        if not backtest_results_by_holding:
            return {'optimal_holding_days': self.default_holding_days}
        
        best_holding = None
        best_score = -np.inf
        holding_scores = {}
        
        for holding_days, results in backtest_results_by_holding.items():
            score = (
                results.get('win_rate', 50) * 0.50 +
                results.get('sharpe_ratio', 0) * 30 -
                (results.get('max_drawdown_pct', 0) * 0.5)
            )
            
            holding_scores[holding_days] = score
            
            if score > best_score:
                best_score = score
                best_holding = holding_days
        
        return {
            'optimal_holding_days': best_holding,
            'optimization_score': round(best_score, 2),
            'all_holdings': holding_scores,
            'recommended_holding_days': best_holding,
            'source': 'model_calibration.py'
        }
    
    def calibrate_risk_parameters(self,
                                 max_position_size_pct: float = 2.0,
                                 max_daily_loss_pct: float = 1.0,
                                 max_monthly_loss_pct: float = 5.0,
                                 portfolio_value: float = 100000) -> Dict:
        """
        Define risk control parameters
        
        Returns: {
            max_position_size,
            max_daily_loss,
            max_monthly_loss,
            stop_loss_pct,
            take_profit_pct
        }
        """
        
        return {
            'max_position_size': round(portfolio_value * (max_position_size_pct / 100), 2),
            'max_daily_loss': round(portfolio_value * (max_daily_loss_pct / 100), 2),
            'max_monthly_loss': round(portfolio_value * (max_monthly_loss_pct / 100), 2),
            'stop_loss_pct': 2.0,  # Exit if down 2%
            'take_profit_pct': 5.0,  # Exit if up 5%
            'risk_reward_ratio': 2.5,
            'max_drawdown_allowed_pct': 10.0,
            'source': 'model_calibration.py'
        }
    
    def calculate_optimal_weights(self,
                                 signal_components: Dict[str, float]) -> Dict:
        """
        Calibrate weights for signal components based on backtest correlation
        
        signal_components: {
            'momentum': 0.15,
            'rsi': 0.10,
            'options': 0.15,
            'analyst': 0.15,
            'insider': 0.10,
            'short_squeeze': 0.08,
            'earnings': 0.10,
            'volatility': 0.05
        }
        
        Returns: {optimized_weights, total_weight, adjustment_made}
        """
        
        if not signal_components:
            return {}
        
        # Check if weights sum to 1.0
        total_weight = sum(signal_components.values())
        
        if abs(total_weight - 1.0) < 0.01:
            adjustment_made = False
            optimized_weights = signal_components
        else:
            # Normalize weights
            adjustment_made = True
            optimized_weights = {}
            
            for component, weight in signal_components.items():
                optimized_weights[component] = weight / total_weight
        
        return {
            'optimized_weights': optimized_weights,
            'total_weight': sum(optimized_weights.values()),
            'adjustment_made': adjustment_made,
            'timestamp': datetime.now().isoformat(),
            'source': 'model_calibration.py'
        }
    
    def generate_calibration_report(self,
                                   threshold_opt: Dict,
                                   holding_opt: Dict,
                                   risk_params: Dict,
                                   backtest_performance: Dict) -> Dict:
        """
        Generate comprehensive calibration report
        
        Returns: {
            recommended_parameters,
            expected_performance,
            risk_profile,
            readiness_score,
            calibration_notes
        }
        """
        
        win_rate = backtest_performance.get('win_rate', 0)
        sharpe = backtest_performance.get('sharpe_ratio', 0)
        max_dd = abs(backtest_performance.get('max_drawdown_pct', 0))
        
        readiness_score = 0
        notes = []
        
        # Threshold readiness
        if threshold_opt.get('optimization_score', 0) > 50:
            readiness_score += 25
        else:
            notes.append('Signal threshold optimization could be improved')
            readiness_score += 10
        
        # Holding period readiness
        if holding_opt.get('optimization_score', 0) > 50:
            readiness_score += 25
        else:
            notes.append('Holding period optimization could be improved')
            readiness_score += 10
        
        # Performance readiness
        if win_rate > 65:
            readiness_score += 25
        elif win_rate > 55:
            readiness_score += 15
        else:
            notes.append(f'Win rate below target: {win_rate}%')
            readiness_score += 5
        
        # Risk readiness
        if max_dd < 15:
            readiness_score += 25
        elif max_dd < 25:
            readiness_score += 15
        else:
            notes.append(f'Max drawdown too high: {max_dd}%')
            readiness_score += 5
        
        return {
            'recommended_parameters': {
                'signal_threshold': threshold_opt.get('optimal_threshold'),
                'holding_days': holding_opt.get('optimal_holding_days'),
                'max_position_size': risk_params.get('max_position_size'),
                'stop_loss_pct': risk_params.get('stop_loss_pct'),
                'take_profit_pct': risk_params.get('take_profit_pct')
            },
            'expected_performance': {
                'win_rate': win_rate,
                'sharpe_ratio': sharpe,
                'max_drawdown': max_dd
            },
            'readiness_score': round(readiness_score, 1),
            'max_readiness': 100,
            'deployment_ready': readiness_score > 70,
            'calibration_notes': notes,
            'timestamp': datetime.now().isoformat(),
            'source': 'model_calibration.py'
        }

if __name__ == "__main__":
    calib = ModelCalibration()
    
    # Test threshold optimization
    threshold_results = {
        55: {'win_rate': 52, 'sharpe_ratio': 0.95, 'max_drawdown_pct': 25},
        60: {'win_rate': 65, 'sharpe_ratio': 1.20, 'max_drawdown_pct': 18},
        65: {'win_rate': 72, 'sharpe_ratio': 1.10, 'max_drawdown_pct': 15},
        70: {'win_rate': 68, 'sharpe_ratio': 0.85, 'max_drawdown_pct': 12}
    }
    
    opt_threshold = calib.optimize_signal_threshold(threshold_results)
    print(f"\nOptimal Signal Threshold: {opt_threshold['optimal_threshold']}")
    
    # Test holding period optimization
    holding_results = {
        3: {'win_rate': 58, 'sharpe_ratio': 0.95, 'max_drawdown_pct': 20},
        5: {'win_rate': 65, 'sharpe_ratio': 1.20, 'max_drawdown_pct': 18},
        10: {'win_rate': 62, 'sharpe_ratio': 1.05, 'max_drawdown_pct': 22}
    }
    
    opt_holding = calib.optimize_holding_period(holding_results)
    print(f"Optimal Holding Period: {opt_holding['optimal_holding_days']} days")
