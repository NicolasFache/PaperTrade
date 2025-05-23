import random
import numpy as np
from datetime import datetime, timedelta
import sqlite3
import logging
import time

logger = logging.getLogger(__name__)

class MarketSimulator:
    """Simulates market movements for testing the trading bot"""
    
    def __init__(self, volatility_factor=1.0):
        self.volatility_factor = volatility_factor
        self.simulated_prices = {}
        self.previous_closes = {}
        
    def initialize_stock(self, symbol: str, base_price: float = None):
        """Initialize a stock with a base price"""
        if base_price is None:
            # Generate random price between $10 and $500
            base_price = random.uniform(10, 500)
        
        self.previous_closes[symbol] = base_price
        self.simulated_prices[symbol] = base_price
        return base_price
    
    def simulate_price_movement(self, symbol: str, current_price: float = None):
        """Simulate realistic price movement for a stock"""
        if symbol not in self.simulated_prices:
            self.initialize_stock(symbol, current_price)
        
        # Get the previous close
        prev_close = self.previous_closes.get(symbol, self.simulated_prices[symbol])
        
        # Simulate different market scenarios
        scenario = random.choices(
            ['normal', 'volatile', 'trending_up', 'trending_down', 'major_event'],
            weights=[0.7, 0.15, 0.05, 0.05, 0.05]
        )[0]
        
        if scenario == 'normal':
            # Normal trading day: -2% to +2%
            change_pct = random.gauss(0, 0.01) * self.volatility_factor
        elif scenario == 'volatile':
            # Volatile day: -4% to +4%
            change_pct = random.gauss(0, 0.02) * self.volatility_factor
        elif scenario == 'trending_up':
            # Bullish trend: 0% to +6%
            change_pct = abs(random.gauss(0.02, 0.02)) * self.volatility_factor
        elif scenario == 'trending_down':
            # Bearish trend: -6% to 0%
            change_pct = -abs(random.gauss(0.02, 0.02)) * self.volatility_factor
        else:  # major_event
            # Major news event: -10% to +10%
            change_pct = random.gauss(0, 0.05) * self.volatility_factor
        
        # Apply realistic constraints
        change_pct = max(-0.15, min(0.15, change_pct))  # Cap at ±15%
        
        # Calculate new price
        new_price = prev_close * (1 + change_pct)
        self.simulated_prices[symbol] = new_price
        
        logger.debug(f"Simulated {symbol}: ${prev_close:.2f} -> ${new_price:.2f} ({change_pct*100:+.2f}%)")
        
        return new_price, change_pct
    
    def simulate_market_day(self, symbols: list):
        """Simulate a full market day for multiple symbols"""
        results = {}
        
        # Decide on overall market direction
        market_trend = random.choices(
            ['bull', 'bear', 'neutral'],
            weights=[0.3, 0.3, 0.4]
        )[0]
        
        logger.info(f"Simulating {market_trend} market day for {len(symbols)} stocks")
        
        for symbol in symbols:
            # Add market bias based on trend
            if market_trend == 'bull':
                self.volatility_factor = random.uniform(0.8, 1.5)
            elif market_trend == 'bear':
                self.volatility_factor = random.uniform(0.8, 1.5)
            else:
                self.volatility_factor = random.uniform(0.5, 1.2)
            
            new_price, change_pct = self.simulate_price_movement(symbol)
            results[symbol] = {
                'price': new_price,
                'change_pct': change_pct,
                'prev_close': self.previous_closes.get(symbol, new_price)
            }
        
        return results
    
    def get_interesting_stocks(self, num_stocks=20):
        """Generate a list of stocks with interesting movements"""
        stocks = []
        
        # Generate some stocks that will definitely trigger trades
        for i in range(num_stocks):
            symbol = f"SIM{i:03d}"
            
            if i < 3:
                # Force some big movers for testing
                if i == 0:
                    # Big drop
                    change = random.uniform(-0.06, -0.08)
                elif i == 1:
                    # Big gain
                    change = random.uniform(0.06, 0.08)
                else:
                    # Near threshold
                    change = random.choice([-0.045, 0.045])
                
                price = random.uniform(50, 200)
                self.previous_closes[symbol] = price
                self.simulated_prices[symbol] = price * (1 + change)
            
            stocks.append(symbol)
        
        return stocks


class SimulatedPaperTradingBot:
    """Modified bot that uses simulated data for testing"""
    
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.simulator = MarketSimulator()
        self.original_get_price = bot_instance.get_current_price
        self.original_calculate_change = bot_instance.calculate_daily_change
        self.original_get_stocks = bot_instance.get_all_tradable_stocks
        
    def enable_simulation(self):
        """Replace real market functions with simulated ones"""
        self.bot.get_current_price = self._simulated_get_price
        self.bot.calculate_daily_change = self._simulated_calculate_change
        self.bot.get_all_tradable_stocks = self._simulated_get_stocks
        logger.info("📊 SIMULATION MODE ENABLED - Using simulated market data")
        
    def _simulated_get_stocks(self):
        """Return simulated stock list"""
        return self.simulator.get_interesting_stocks(50)
    
    def _simulated_get_price(self, symbol: str):
        """Get simulated price"""
        if symbol not in self.simulator.simulated_prices:
            self.simulator.initialize_stock(symbol)
        return self.simulator.simulated_prices[symbol]
    
    def _simulated_calculate_change(self, symbol: str):
        """Calculate simulated daily change"""
        if symbol not in self.simulator.simulated_prices:
            price, change = self.simulator.simulate_price_movement(symbol)
        else:
            price = self.simulator.simulated_prices[symbol]
            prev = self.simulator.previous_closes.get(symbol, price)
            change = (price - prev) / prev if prev != 0 else 0
        
        return price, change
    
    def run_simulation_test(self):
        """Run a test with simulated market data"""
        logger.info("Starting simulation test...")
        
        # Simulate market movements
        stocks = self._simulated_get_stocks()
        results = self.simulator.simulate_market_day(stocks)
        
        # Show some interesting movements
        big_movers = sorted(
            [(s, r['change_pct']) for s, r in results.items()],
            key=lambda x: abs(x[1]),
            reverse=True
        )[:10]
        
        logger.info("\n🎲 Simulated market movements (top 10):")
        for symbol, change in big_movers:
            logger.info(f"  {symbol}: {change*100:+.2f}%")
        
        # Run the bot scan
        self.bot.run_scan()
        
        return results


# Standalone test function
def run_simulation_test():
    """Run a standalone simulation test"""
    import sys
    import os
    from dotenv import load_dotenv
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    load_dotenv()
    
    # Import the main bot
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from paperTradingBot import PaperTradingBot
    
    # Create bot with test thresholds
    bot = PaperTradingBot(test_thresholds=True)
    
    # Wrap it with simulator
    sim_bot = SimulatedPaperTradingBot(bot)
    sim_bot.enable_simulation()
    
    # Run simulation
    logger.info("=" * 60)
    logger.info("Running Paper Trading Bot with Simulated Market Data")
    logger.info("This will generate fake price movements to test trading logic")
    logger.info("=" * 60)
    
    sim_bot.run_simulation_test()
    
    # Show portfolio
    summary = bot.get_portfolio_summary()
    logger.info(f"\n📈 Portfolio after simulation:")
    logger.info(f"  Total Value: ${summary['total_value']:.2f}")
    logger.info(f"  Positions: {len(summary['positions'])}")
    
    if summary['recent_trades']:
        logger.info(f"\n🔄 Recent trades:")
        for trade in summary['recent_trades'][:5]:
            logger.info(f"  {trade[1]} {trade[0]}: {trade[2]:.4f} shares @ ${trade[3]:.2f}")


if __name__ == "__main__":
    run_simulation_test()