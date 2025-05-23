import alpaca_trade_api as tradeapi
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import json
import sqlite3
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf
from typing import Dict, List, Tuple
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PaperTradingBot:
    def __init__(self, test_thresholds=False):
        # Alpaca API credentials (use paper trading credentials)
        self.api = tradeapi.REST(
            os.getenv('ALPACA_API_KEY'),
            os.getenv('ALPACA_SECRET_KEY'),
            base_url='https://paper-api.alpaca.markets'
        )
        
        # Trading parameters
        self.trade_amount = 10  # $10 per trade
        
        # Use lower thresholds for testing if specified
        if test_thresholds:
            self.buy_threshold = -0.02  # -2% drop for testing
            self.sell_threshold = 0.02  # +2% gain for testing
            logger.info("Using TEST THRESHOLDS: Buy at -2%, Sell at +2%")
        else:
            self.buy_threshold = -0.05  # -5% drop
            self.sell_threshold = 0.05  # +5% gain
            logger.info("Using NORMAL THRESHOLDS: Buy at -5%, Sell at +5%")
        
        # Initialize database
        self.init_database()
        
        # Cache for stock prices
        self.price_cache = {}
        self.last_update = {}
        
        # Track stocks close to thresholds
        self.close_to_threshold = []
        
    def init_database(self):
        """Initialize SQLite database for tracking trades and price history"""
        self.conn = sqlite3.connect('paper_trading.db', check_same_thread=False)
        cursor = self.conn.cursor()
        
        # Create tables
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
        
    def get_all_tradable_stocks(self) -> List[str]:
        """Get list of all tradable US stocks from Alpaca"""
        try:
            assets = self.api.list_assets(status='active', asset_class='us_equity')
            # Filter for tradable stocks only
            tradable_stocks = [
                asset.symbol for asset in assets 
                if asset.tradable and asset.fractionable  # We want fractional shares for $10 trades
            ]
            logger.info(f"Found {len(tradable_stocks)} tradable stocks")
            
            # In test mode, limit to first 100 stocks to reduce API calls
            import sys
            if '--test' in sys.argv and len(tradable_stocks) > 100:
                logger.info("Test mode: Limiting to first 100 stocks")
                tradable_stocks = tradable_stocks[:100]
                
            return tradable_stocks
        except Exception as e:
            logger.error(f"Error fetching tradable stocks: {e}")
            return []
    
    def get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol"""
        try:
            # Check cache first (1-minute cache)
            if symbol in self.price_cache:
                if datetime.now() - self.last_update.get(symbol, datetime.min) < timedelta(minutes=1):
                    return self.price_cache[symbol]
            
            # Get latest trade from Alpaca
            trade = self.api.get_latest_trade(symbol)
            if trade:
                price = trade.price
                self.price_cache[symbol] = price
                self.last_update[symbol] = datetime.now()
                return price
            return None
        except Exception as e:
            # Don't log every single error in detail to avoid spam
            if "sleep" not in str(e).lower():  # Only log non-rate-limit errors
                logger.debug(f"Error getting price for {symbol}: {e}")
            return None
    
    def calculate_daily_change(self, symbol: str) -> Tuple[float, float]:
        """Calculate daily price change percentage"""
        try:
            # Get current price
            current_price = self.get_current_price(symbol)
            if not current_price:
                return None, None
            
            # Get previous close from Alpaca
            # Format datetime properly for Alpaca API (RFC3339 format)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=3)
            
            # Use pagination parameter to avoid issues
            bars = self.api.get_bars(
                symbol,
                '1Day',
                start=start_date.strftime('%Y-%m-%d'),
                end=end_date.strftime('%Y-%m-%d'),
                limit=2,
                page_limit=2,
                adjustment='raw'
            ).df
            
            if bars is not None and len(bars) >= 1:
                prev_close = bars.iloc[-2]['close'] if len(bars) > 1 else bars.iloc[-1]['open']
                change_pct = (current_price - prev_close) / prev_close if prev_close != 0 else 0
                return current_price, change_pct
            
            return current_price, 0.0
        except Exception as e:
            # Don't log every single error in detail to avoid spam
            if "sleep" not in str(e).lower():  # Only log non-rate-limit errors
                logger.debug(f"Error calculating change for {symbol}: {e}")
            return None, None
    
    def should_buy(self, symbol: str, change_pct: float) -> bool:
        """Check if we should buy based on criteria"""
        if change_pct <= self.buy_threshold:
            # Check if we don't have too much exposure
            cursor = self.conn.cursor()
            cursor.execute('SELECT quantity FROM positions WHERE symbol = ?', (symbol,))
            position = cursor.fetchone()
            
            # Limit position size to $100 per stock
            if position and position[0] * self.get_current_price(symbol) >= 100:
                return False
            return True
        return False
    
    def should_sell(self, symbol: str, change_pct: float) -> bool:
        """Check if we should sell based on criteria"""
        if change_pct >= self.sell_threshold:
            # Check if we have a position
            cursor = self.conn.cursor()
            cursor.execute('SELECT quantity FROM positions WHERE symbol = ?', (symbol,))
            position = cursor.fetchone()
            return position is not None and position[0] > 0
        return False
    
    def execute_trade(self, symbol: str, action: str, price: float, reason: str):
        """Execute a paper trade through Alpaca"""
        try:
            quantity = self.trade_amount / price
            
            if action == 'buy':
                order = self.api.submit_order(
                    symbol=symbol,
                    qty=quantity,
                    side='buy',
                    type='market',
                    time_in_force='day'
                )
                logger.info(f"BUY order placed: {symbol} - {quantity:.4f} shares at ${price:.2f}")
            else:  # sell
                # Check current position
                cursor = self.conn.cursor()
                cursor.execute('SELECT quantity FROM positions WHERE symbol = ?', (symbol,))
                position = cursor.fetchone()
                
                if position and position[0] > 0:
                    sell_qty = min(quantity, position[0])
                    order = self.api.submit_order(
                        symbol=symbol,
                        qty=sell_qty,
                        side='sell',
                        type='market',
                        time_in_force='day'
                    )
                    logger.info(f"SELL order placed: {symbol} - {sell_qty:.4f} shares at ${price:.2f}")
                else:
                    logger.warning(f"No position to sell for {symbol}")
                    return
            
            # Record trade in database
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO trades (symbol, timestamp, action, quantity, price, amount, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (symbol, datetime.now(), action, quantity, price, self.trade_amount, reason))
            
            # Update positions
            if action == 'buy':
                cursor.execute('''
                    INSERT OR REPLACE INTO positions (symbol, quantity, avg_price, last_update)
                    VALUES (?, 
                        COALESCE((SELECT quantity FROM positions WHERE symbol = ?), 0) + ?,
                        ?, ?)
                ''', (symbol, symbol, quantity, price, datetime.now()))
            else:
                cursor.execute('''
                    UPDATE positions 
                    SET quantity = quantity - ?, last_update = ?
                    WHERE symbol = ?
                ''', (quantity, datetime.now(), symbol))
            
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"Error executing trade for {symbol}: {e}")
    
    def process_stock(self, symbol: str):
        """Process a single stock for trading signals"""
        try:
            current_price, change_pct = self.calculate_daily_change(symbol)
            
            if current_price is None or change_pct is None:
                return
            
            # Track stocks close to thresholds (within 1% of threshold)
            if abs(change_pct - self.buy_threshold) < 0.01 or abs(change_pct - self.sell_threshold) < 0.01:
                self.close_to_threshold.append({
                    'symbol': symbol,
                    'price': current_price,
                    'change_pct': change_pct * 100
                })
            
            # Record price history
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO price_history 
                (symbol, timestamp, price, daily_change_pct)
                VALUES (?, ?, ?, ?)
            ''', (symbol, datetime.now(), current_price, change_pct))
            self.conn.commit()
            
            # Check trading signals
            if self.should_buy(symbol, change_pct):
                logger.info(f"🔵 BUY SIGNAL: {symbol} dropped {change_pct*100:.2f}% to ${current_price:.2f}")
                self.execute_trade(symbol, 'buy', current_price, 
                                 f"Price dropped {change_pct*100:.2f}%")
            elif self.should_sell(symbol, change_pct):
                logger.info(f"🔴 SELL SIGNAL: {symbol} gained {change_pct*100:.2f}% to ${current_price:.2f}")
                self.execute_trade(symbol, 'sell', current_price, 
                                 f"Price increased {change_pct*100:.2f}%")
                
        except Exception as e:
            if "sleep" not in str(e).lower():
                logger.error(f"Error processing {symbol}: {e}")
    
    def run_scan(self):
        """Run a full scan of all tradable stocks"""
        logger.info("Starting market scan...")
        stocks = self.get_all_tradable_stocks()
        
        # Reset close to threshold tracker
        self.close_to_threshold = []
        
        # Progress tracking
        processed = 0
        trades_found = 0
        
        # Process stocks in batches using thread pool
        batch_size = 20  # Reduced batch size to avoid rate limits
        with ThreadPoolExecutor(max_workers=5) as executor:  # Reduced workers
            for i in range(0, len(stocks), batch_size):
                batch = stocks[i:i+batch_size]
                futures = {executor.submit(self.process_stock, symbol): symbol 
                          for symbol in batch}
                
                for future in as_completed(futures):
                    symbol = futures[future]
                    try:
                        future.result()
                        processed += 1
                        if processed % 20 == 0:
                            logger.info(f"Progress: {processed}/{len(stocks)} stocks processed...")
                    except Exception as e:
                        logger.error(f"Error processing {symbol}: {e}")
                
                # Increased delay between batches to avoid rate limits
                time.sleep(1)
        
        logger.info(f"Market scan completed: {processed} stocks processed")
        
        # Show stocks close to thresholds
        if self.close_to_threshold:
            logger.info(f"\n📊 Stocks close to thresholds (within 1%):")
            # Sort by how close they are to thresholds
            self.close_to_threshold.sort(key=lambda x: min(
                abs(x['change_pct']/100 - self.buy_threshold),
                abs(x['change_pct']/100 - self.sell_threshold)
            ))
            for stock in self.close_to_threshold[:10]:  # Show top 10
                logger.info(f"  {stock['symbol']}: {stock['change_pct']:+.2f}% (${stock['price']:.2f})")
    
    def get_portfolio_summary(self):
        """Get current portfolio summary"""
        cursor = self.conn.cursor()
        
        # Get all positions
        cursor.execute('''
            SELECT symbol, quantity, avg_price 
            FROM positions 
            WHERE quantity > 0
        ''')
        positions = cursor.fetchall()
        
        # Get recent trades
        cursor.execute('''
            SELECT symbol, action, quantity, price, timestamp 
            FROM trades 
            ORDER BY timestamp DESC 
            LIMIT 10
        ''')
        recent_trades = cursor.fetchall()
        
        # Calculate portfolio value
        total_value = 0
        position_details = []
        for symbol, quantity, avg_price in positions:
            current_price = self.get_current_price(symbol)
            if current_price:
                value = quantity * current_price
                total_value += value
                pnl = (current_price - avg_price) * quantity
                pnl_pct = (current_price - avg_price) / avg_price * 100
                position_details.append({
                    'symbol': symbol,
                    'quantity': quantity,
                    'avg_price': avg_price,
                    'current_price': current_price,
                    'value': value,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct
                })
        
        return {
            'total_value': total_value,
            'positions': position_details,
            'recent_trades': recent_trades
        }
    
    def run(self, test_mode=False):
        """Main run loop
        
        Args:
            test_mode: If True, runs even when market is closed (for testing)
        """
        logger.info("Starting Paper Trading Bot...")
        
        if test_mode:
            logger.warning("RUNNING IN TEST MODE - Will scan even if market is closed")
            logger.warning("Note: Price data may be stale outside market hours")
        
        # Check if market is open
        clock = self.api.get_clock()
        
        while True:
            try:
                clock = self.api.get_clock()
                
                if clock.is_open or test_mode:
                    if not clock.is_open:
                        logger.info("Market is closed but running in TEST MODE")
                    
                    logger.info("Running scan...")
                    self.run_scan()
                    
                    # Show portfolio summary
                    summary = self.get_portfolio_summary()
                    logger.info(f"Portfolio Value: ${summary['total_value']:.2f}")
                    logger.info(f"Active Positions: {len(summary['positions'])}")
                    
                    # Wait 5 minutes before next scan
                    time.sleep(120)
                else:
                    next_open = clock.next_open
                    logger.info(f"Market is closed. Next open: {next_open}")
                    logger.info("To run anyway, use test mode: python paper_trading_bot.py --test")
                    # Wait 30 minutes and check again
                    time.sleep(1800)
                    
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(60)  # Wait a minute before retrying

if __name__ == "__main__":
    import sys
    
    # Check for test mode flag
    test_mode = '--test' in sys.argv
    test_thresholds = '--test-thresholds' in sys.argv
    
    # Show help if requested
    if '--help' in sys.argv:
        print("""
Paper Trading Bot - Options:
  --test             Run even when market is closed
  --test-thresholds  Use lower thresholds (±2% instead of ±5%) for testing
  --help            Show this help message
  
Examples:
  python paper_trading_bot.py                    # Normal mode (market hours only, ±5%)
  python paper_trading_bot.py --test             # Test mode (any time, ±5%)
  python paper_trading_bot.py --test --test-thresholds  # Test with ±2% thresholds
        """)
        sys.exit(0)
    
    bot = PaperTradingBot(test_thresholds=test_thresholds)
    bot.run(test_mode=test_mode)