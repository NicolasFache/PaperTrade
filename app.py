from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import sqlite3
import json
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objs as go
import plotly.utils

app = Flask(__name__)
CORS(app)

def get_db_connection():
    conn = sqlite3.connect('paper_trading.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/portfolio')
def get_portfolio():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get positions
    cursor.execute('''
        SELECT p.symbol, p.quantity, p.avg_price,
               h.price as current_price, h.daily_change_pct
        FROM positions p
        LEFT JOIN (
            SELECT symbol, price, daily_change_pct,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY timestamp DESC) as rn
            FROM price_history
        ) h ON p.symbol = h.symbol AND h.rn = 1
        WHERE p.quantity > 0
    ''')
    
    positions = []
    total_value = 0
    total_cost = 0
    
    for row in cursor.fetchall():
        if row['current_price']:
            value = row['quantity'] * row['current_price']
            cost = row['quantity'] * row['avg_price']
            pnl = value - cost
            pnl_pct = (pnl / cost) * 100 if cost > 0 else 0
            
            positions.append({
                'symbol': row['symbol'],
                'quantity': round(row['quantity'], 4),
                'avg_price': round(row['avg_price'], 2),
                'current_price': round(row['current_price'], 2),
                'value': round(value, 2),
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 2),
                'daily_change_pct': round(row['daily_change_pct'] * 100, 2) if row['daily_change_pct'] else 0
            })
            
            total_value += value
            total_cost += cost
    
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost) * 100 if total_cost > 0 else 0
    
    conn.close()
    
    return jsonify({
        'positions': positions,
        'summary': {
            'total_value': round(total_value, 2),
            'total_cost': round(total_cost, 2),
            'total_pnl': round(total_pnl, 2),
            'total_pnl_pct': round(total_pnl_pct, 2),
            'position_count': len(positions)
        }
    })

@app.route('/api/trades')
def get_trades():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get limit from query params
    limit = request.args.get('limit', 50, type=int)
    
    cursor.execute('''
        SELECT symbol, timestamp, action, quantity, price, amount, reason
        FROM trades
        ORDER BY timestamp DESC
        LIMIT ?
    ''', (limit,))
    
    trades = []
    for row in cursor.fetchall():
        trades.append({
            'symbol': row['symbol'],
            'timestamp': row['timestamp'],
            'action': row['action'],
            'quantity': round(row['quantity'], 4),
            'price': round(row['price'], 2),
            'amount': round(row['amount'], 2),
            'reason': row['reason']
        })
    
    conn.close()
    return jsonify({'trades': trades})

@app.route('/api/performance')
def get_performance():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get daily P&L
    cursor.execute('''
        SELECT DATE(timestamp) as date,
               SUM(CASE WHEN action = 'buy' THEN -amount ELSE amount END) as daily_pnl
        FROM trades
        GROUP BY DATE(timestamp)
        ORDER BY date
    ''')
    
    daily_pnl = []
    cumulative_pnl = 0
    for row in cursor.fetchall():
        cumulative_pnl += row['daily_pnl']
        daily_pnl.append({
            'date': row['date'],
            'daily_pnl': round(row['daily_pnl'], 2),
            'cumulative_pnl': round(cumulative_pnl, 2)
        })
    
    # Get trade statistics
    cursor.execute('''
        SELECT 
            COUNT(*) as total_trades,
            SUM(CASE WHEN action = 'buy' THEN 1 ELSE 0 END) as buy_trades,
            SUM(CASE WHEN action = 'sell' THEN 1 ELSE 0 END) as sell_trades,
            COUNT(DISTINCT symbol) as unique_symbols,
            COUNT(DISTINCT DATE(timestamp)) as trading_days
        FROM trades
    ''')
    
    stats = cursor.fetchone()
    
    conn.close()
    
    return jsonify({
        'daily_pnl': daily_pnl,
        'statistics': {
            'total_trades': stats['total_trades'],
            'buy_trades': stats['buy_trades'],
            'sell_trades': stats['sell_trades'],
            'unique_symbols': stats['unique_symbols'],
            'trading_days': stats['trading_days'],
            'avg_trades_per_day': round(stats['total_trades'] / stats['trading_days'], 1) if stats['trading_days'] > 0 else 0
        }
    })

@app.route('/api/chart/<symbol>')
def get_stock_chart(symbol):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get price history
    cursor.execute('''
        SELECT timestamp, price, daily_change_pct
        FROM price_history
        WHERE symbol = ?
        ORDER BY timestamp DESC
        LIMIT 100
    ''', (symbol,))
    
    data = []
    for row in cursor.fetchall():
        data.append({
            'timestamp': row['timestamp'],
            'price': row['price'],
            'change_pct': row['daily_change_pct'] * 100 if row['daily_change_pct'] else 0
        })
    
    # Get trades for this symbol
    cursor.execute('''
        SELECT timestamp, action, price
        FROM trades
        WHERE symbol = ?
        ORDER BY timestamp DESC
    ''', (symbol,))
    
    trades = []
    for row in cursor.fetchall():
        trades.append({
            'timestamp': row['timestamp'],
            'action': row['action'],
            'price': row['price']
        })
    
    conn.close()
    
    return jsonify({
        'price_data': data,
        'trades': trades
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)