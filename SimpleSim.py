#!/usr/bin/env python3
"""
Standalone test script for the paper trading bot with simulated data.
This avoids import issues and segmentation faults.
"""

import random
import sqlite3
import logging
from datetime import datetime
import time
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SimpleSimulator:
    """Simplified trading simulator for testing"""
    
    def __init__(self, db_path='paper_trading.db'):
        self.conn = sqlite3.connect(db_path)
        self.init_database()
        self.trades_executed = []
        
    def init_database(self):
        """Initialize the database tables"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                symbol TEXT,
                timestamp DATETIME,
                price REAL,
                daily_change_pct REAL,
                PRIMARY KEY (symbol, timestamp)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timestamp DATETIME,
                action TEXT,
                quantity REAL,
                price REAL,
                amount REAL,
                reason TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                quantity REAL,
                avg_price REAL,
                last_update DATETIME
            )
        ''')
        
        self.conn.commit()
        
    def generate_test_data(self, num_stocks=30):
        """Generate test stocks with various price movements"""
        stocks = []
        
        for i in range(num_stocks):
            symbol = f"TEST{i:03d}"
            base_price = random.uniform(20, 300)
            
            # Determine price movement
            if i < 5:
                # Guarantee some big movers
                if i == 0:
                    change_pct = -0.065  # -6.5%
                elif i == 1:
                    change_pct = 0.058   # +5.8%
                elif i == 2:
                    change_pct = -0.052  # -5.2%
                elif i == 3:
                    change_pct = 0.055   # +5.5%
                else:
                    change_pct = random.choice([-0.048, 0.048])  # Near threshold
            else:
                # Random movements
                change_pct = random.gauss(0, 0.02)
                change_pct = max(-0.10, min(0.10, change_pct))  # Cap at ±10%
            
            current_price = base_price * (1 + change_pct)
            
            stocks.append({
                'symbol': symbol,
                'base_price': base_price,
                'current_price': current_price,
                'change_pct': change_pct
            })
            
        return stocks
    
    def simulate_trades(self, stocks, buy_threshold=-0.05, sell_threshold=0.05):
        """Simulate trading based on thresholds"""
        logger.info(f"\n📊 Simulating trades with thresholds: Buy at {buy_threshold*100:.1f}%, Sell at {sell_threshold*100:.1f}%\n")
        
        for stock in stocks:
            symbol = stock['symbol']
            price = stock['current_price']
            change_pct = stock['change_pct']
            
            # Record price history
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO price_history 
                (symbol, timestamp, price, daily_change_pct)
                VALUES (?, ?, ?, ?)
            ''', (symbol, datetime.now(), price, change_pct))
            
            # Check for trades
            if change_pct <= buy_threshold:
                # Execute buy
                quantity = 10.0 / price  # $10 worth
                
                logger.info(f"🔵 BUY SIGNAL: {symbol} dropped {change_pct*100:.2f}% to ${price:.2f}")
                logger.info(f"   Buying {quantity:.4f} shares for $10.00")
                
                # Record trade
                cursor.execute('''
                    INSERT INTO trades (symbol, timestamp, action, quantity, price, amount, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (symbol, datetime.now(), 'buy', quantity, price, 10.0, 
                      f"Price dropped {change_pct*100:.2f}%"))
                
                # Update position
                cursor.execute('''
                    INSERT OR REPLACE INTO positions (symbol, quantity, avg_price, last_update)
                    VALUES (?, ?, ?, ?)
                ''', (symbol, quantity, price, datetime.now()))
                
                self.trades_executed.append(('buy', symbol, price, change_pct))
                
            elif change_pct >= sell_threshold:
                # For simulation, assume we have a position to sell
                quantity = 10.0 / price  # $10 worth
                
                logger.info(f"🔴 SELL SIGNAL: {symbol} gained {change_pct*100:.2f}% to ${price:.2f}")
                logger.info(f"   Selling {quantity:.4f} shares for $10.00")
                
                # Record trade
                cursor.execute('''
                    INSERT INTO trades (symbol, timestamp, action, quantity, price, amount, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (symbol, datetime.now(), 'sell', quantity, price, 10.0, 
                      f"Price increased {change_pct*100:.2f}%"))
                
                self.trades_executed.append(('sell', symbol, price, change_pct))
            
            # Show near-misses
            elif abs(change_pct - buy_threshold) < 0.01 or abs(change_pct - sell_threshold) < 0.01:
                logger.info(f"📍 Near threshold: {symbol} moved {change_pct*100:+.2f}% to ${price:.2f}")
        
        self.conn.commit()
        
    def show_summary(self):
        """Show summary of simulation results"""
        cursor = self.conn.cursor()
        
        # Count trades
        cursor.execute('SELECT COUNT(*) FROM trades WHERE DATE(timestamp) = DATE("now")')
        total_trades = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM trades WHERE action = "buy" AND DATE(timestamp) = DATE("now")')
        buy_trades = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM trades WHERE action = "sell" AND DATE(timestamp) = DATE("now")')
        sell_trades = cursor.fetchone()[0]
        
        # Get positions
        cursor.execute('SELECT COUNT(*) FROM positions WHERE quantity > 0')
        active_positions = cursor.fetchone()[0]
        
        logger.info(f"\n📈 SIMULATION RESULTS:")
        logger.info(f"=" * 50)
        logger.info(f"Total trades executed: {total_trades}")
        logger.info(f"  - Buy orders:  {buy_trades}")
        logger.info(f"  - Sell orders: {sell_trades}")
        logger.info(f"Active positions: {active_positions}")
        
        if self.trades_executed:
            logger.info(f"\n🔄 Trades executed this session:")
            for action, symbol, price, change in self.trades_executed:
                icon = "🔵" if action == "buy" else "🔴"
                logger.info(f"  {icon} {action.upper()}: {symbol} at ${price:.2f} ({change*100:+.2f}%)")
        
        # Show recent trades from database
        cursor.execute('''
            SELECT symbol, action, quantity, price, reason 
            FROM trades 
            ORDER BY timestamp DESC 
            LIMIT 5
        ''')
        recent_trades = cursor.fetchall()
        
        if recent_trades:
            logger.info(f"\n📋 Recent trades in database:")
            for trade in recent_trades:
                logger.info(f"  {trade[1].upper()} {trade[0]}: {trade[2]:.4f} shares @ ${trade[3]:.2f} - {trade[4]}")

def main():
    """Run the simulation"""
    logger.info("=" * 60)
    logger.info("PAPER TRADING BOT - SIMULATION TEST")
    logger.info("This creates fake stocks with price movements to test trading")
    logger.info("=" * 60)
    
    # Check for test thresholds flag
    import sys
    use_test_thresholds = '--test-thresholds' in sys.argv
    
    if use_test_thresholds:
        buy_threshold = -0.02
        sell_threshold = 0.02
        logger.info("Using TEST THRESHOLDS: ±2%")
    else:
        buy_threshold = -0.05
        sell_threshold = 0.05
        logger.info("Using NORMAL THRESHOLDS: ±5%")
    
    # Create simulator
    sim = SimpleSimulator()
    
    # Generate test data
    logger.info("\n🎲 Generating test market data...")
    stocks = sim.generate_test_data(30)
    
    # Show market overview
    logger.info(f"\n📊 Market overview (showing biggest movers):")
    sorted_stocks = sorted(stocks, key=lambda x: abs(x['change_pct']), reverse=True)[:10]
    for stock in sorted_stocks:
        logger.info(f"  {stock['symbol']}: {stock['change_pct']*100:+.2f}% (${stock['current_price']:.2f})")
    
    # Simulate trades
    sim.simulate_trades(stocks, buy_threshold, sell_threshold)
    
    # Show summary
    sim.show_summary()
    
    logger.info("\n✅ Simulation complete! Check the dashboard to see your trades.")
    logger.info("   Run: python app.py")
    logger.info("   Visit: http://localhost:5000")

if __name__ == "__main__":
    main()