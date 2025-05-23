from flask import Flask, render_template_string, jsonify, request
from flask_cors import CORS
import sqlite3
import json
from datetime import datetime, timedelta
import pandas as pd
import os

app = Flask(__name__)
CORS(app)

# HTML template embedded in Python file for easier deployment
DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Paper Trading Bot Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .positive { color: #10b981; }
        .negative { color: #ef4444; }
    </style>
</head>
<body class="bg-gray-100">
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold mb-8 text-gray-800">Paper Trading Bot Dashboard</h1>
        
        <!-- Portfolio Summary -->
        <div class="bg-white rounded-lg shadow-md p-6 mb-8">
            <h2 class="text-2xl font-semibold mb-4">Portfolio Summary</h2>
            <div class="grid grid-cols-1 md:grid-cols-5 gap-4">
                <div class="text-center">
                    <p class="text-gray-600 text-sm">Total Value</p>
                    <p class="text-2xl font-bold" id="totalValue">$0.00</p>
                </div>
                <div class="text-center">
                    <p class="text-gray-600 text-sm">Total Cost</p>
                    <p class="text-2xl font-bold" id="totalCost">$0.00</p>
                </div>
                <div class="text-center">
                    <p class="text-gray-600 text-sm">Total P&L</p>
                    <p class="text-2xl font-bold" id="totalPnL">$0.00</p>
                </div>
                <div class="text-center">
                    <p class="text-gray-600 text-sm">Total P&L %</p>
                    <p class="text-2xl font-bold" id="totalPnLPct">0.00%</p>
                </div>
                <div class="text-center">
                    <p class="text-gray-600 text-sm">Positions</p>
                    <p class="text-2xl font-bold" id="positionCount">0</p>
                </div>
            </div>
        </div>
        
        <!-- Performance Chart -->
        <div class="bg-white rounded-lg shadow-md p-6 mb-8">
            <h2 class="text-2xl font-semibold mb-4">Cumulative P&L</h2>
            <div style="height: 300px;">
                <canvas id="performanceChart"></canvas>
            </div>
        </div>
        
        <!-- Positions Table -->
        <div class="bg-white rounded-lg shadow-md p-6 mb-8">
            <h2 class="text-2xl font-semibold mb-4">Current Positions</h2>
            <div class="overflow-x-auto">
                <table class="w-full text-left">
                    <thead>
                        <tr class="border-b">
                            <th class="py-2">Symbol</th>
                            <th class="py-2">Quantity</th>
                            <th class="py-2">Avg Price</th>
                            <th class="py-2">Current Price</th>
                            <th class="py-2">Value</th>
                            <th class="py-2">P&L</th>
                            <th class="py-2">P&L %</th>
                            <th class="py-2">Daily Change</th>
                        </tr>
                    </thead>
                    <tbody id="positionsTable">
                        <!-- Positions will be inserted here -->
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Recent Trades -->
        <div class="bg-white rounded-lg shadow-md p-6">
            <h2 class="text-2xl font-semibold mb-4">Recent Trades</h2>
            <div class="overflow-x-auto">
                <table class="w-full text-left">
                    <thead>
                        <tr class="border-b">
                            <th class="py-2">Time</th>
                            <th class="py-2">Symbol</th>
                            <th class="py-2">Action</th>
                            <th class="py-2">Quantity</th>
                            <th class="py-2">Price</th>
                            <th class="py-2">Amount</th>
                            <th class="py-2">Reason</th>
                        </tr>
                    </thead>
                    <tbody id="tradesTable">
                        <!-- Trades will be inserted here -->
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    
    <script>
        let performanceChart;
        
        async function updateDashboard() {
            try {
                // Update portfolio
                const portfolioRes = await fetch('/api/portfolio');
                const portfolioData = await portfolioRes.json();
                
                // Update summary
                document.getElementById('totalValue').textContent = `${portfolioData.summary.total_value.toFixed(2)}`;
                document.getElementById('totalCost').textContent = `${portfolioData.summary.total_cost.toFixed(2)}`;
                document.getElementById('totalPnL').textContent = `${portfolioData.summary.total_pnl.toFixed(2)}`;
                document.getElementById('totalPnL').className = portfolioData.summary.total_pnl >= 0 ? 'text-2xl font-bold positive' : 'text-2xl font-bold negative';
                document.getElementById('totalPnLPct').textContent = `${portfolioData.summary.total_pnl_pct.toFixed(2)}%`;
                document.getElementById('totalPnLPct').className = portfolioData.summary.total_pnl_pct >= 0 ? 'text-2xl font-bold positive' : 'text-2xl font-bold negative';
                document.getElementById('positionCount').textContent = portfolioData.summary.position_count;
                
                // Update positions table
                const positionsTable = document.getElementById('positionsTable');
                positionsTable.innerHTML = '';
                portfolioData.positions.forEach(pos => {
                    const row = `
                        <tr class="border-b">
                            <td class="py-2 font-medium">${pos.symbol}</td>
                            <td class="py-2">${pos.quantity}</td>
                            <td class="py-2">${pos.avg_price.toFixed(2)}</td>
                            <td class="py-2">${pos.current_price.toFixed(2)}</td>
                            <td class="py-2">${pos.value.toFixed(2)}</td>
                            <td class="py-2 ${pos.pnl >= 0 ? 'positive' : 'negative'}">${pos.pnl.toFixed(2)}</td>
                            <td class="py-2 ${pos.pnl_pct >= 0 ? 'positive' : 'negative'}">${pos.pnl_pct.toFixed(2)}%</td>
                            <td class="py-2 ${pos.daily_change_pct >= 0 ? 'positive' : 'negative'}">${pos.daily_change_pct.toFixed(2)}%</td>
                        </tr>
                    `;
                    positionsTable.innerHTML += row;
                });
                
                // Update trades
                const tradesRes = await fetch('/api/trades');
                const tradesData = await tradesRes.json();
                
                const tradesTable = document.getElementById('tradesTable');
                tradesTable.innerHTML = '';
                tradesData.trades.forEach(trade => {
                    const time = new Date(trade.timestamp).toLocaleString();
                    const row = `
                        <tr class="border-b">
                            <td class="py-2 text-sm">${time}</td>
                            <td class="py-2 font-medium">${trade.symbol}</td>
                            <td class="py-2 ${trade.action === 'buy' ? 'positive' : 'negative'}">${trade.action.toUpperCase()}</td>
                            <td class="py-2">${trade.quantity}</td>
                            <td class="py-2">${trade.price.toFixed(2)}</td>
                            <td class="py-2">${trade.amount.toFixed(2)}</td>
                            <td class="py-2 text-sm text-gray-600">${trade.reason}</td>
                        </tr>
                    `;
                    tradesTable.innerHTML += row;
                });
                
                // Update performance chart
                const perfRes = await fetch('/api/performance');
                const perfData = await perfRes.json();
                
                const chartData = {
                    labels: perfData.daily_pnl.map(d => d.date),
                    datasets: [{
                        label: 'Cumulative P&L',
                        data: perfData.daily_pnl.map(d => d.cumulative_pnl),
                        borderColor: 'rgb(59, 130, 246)',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        fill: true,
                        tension: 0.1
                    }]
                };
                
                if (performanceChart) {
                    performanceChart.data = chartData;
                    performanceChart.update();
                } else {
                    const ctx = document.getElementById('performanceChart').getContext('2d');
                    performanceChart = new Chart(ctx, {
                        type: 'line',
                        data: chartData,
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: {
                                    display: false
                                },
                                tooltip: {
                                    callbacks: {
                                        label: function(context) {
                                            return ' + context.parsed.y.toFixed(2);
                                        }
                                    }
                                }
                            },
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    ticks: {
                                        callback: function(value) {
                                            return ' + value;
                                        }
                                    }
                                }
                            }
                        }
                    });
                }
            } catch (error) {
                console.error('Error updating dashboard:', error);
            }
        }
        
        // Update dashboard every 30 seconds
        updateDashboard();
        setInterval(updateDashboard, 30000);
    </script>
</body>
</html>'''

def get_db_connection():
    # Check if database exists
    if not os.path.exists('paper_trading.db'):
        return None
    conn = sqlite3.connect('paper_trading.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML)

@app.route('/api/portfolio')
def get_portfolio():
    conn = get_db_connection()
    if not conn:
        return jsonify({'positions': [], 'summary': {
            'total_value': 0, 'total_cost': 0, 'total_pnl': 0, 
            'total_pnl_pct': 0, 'position_count': 0
        }})
    
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
    if not conn:
        return jsonify({'trades': []})
    
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
    if not conn:
        return jsonify({'daily_pnl': [], 'statistics': {
            'total_trades': 0, 'buy_trades': 0, 'sell_trades': 0,
            'unique_symbols': 0, 'trading_days': 0, 'avg_trades_per_day': 0
        }})
    
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
            'total_trades': stats['total_trades'] or 0,
            'buy_trades': stats['buy_trades'] or 0,
            'sell_trades': stats['sell_trades'] or 0,
            'unique_symbols': stats['unique_symbols'] or 0,
            'trading_days': stats['trading_days'] or 0,
            'avg_trades_per_day': round(stats['total_trades'] / stats['trading_days'], 1) if stats['trading_days'] and stats['trading_days'] > 0 else 0
        }
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)