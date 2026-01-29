# NIJA Mobile App Setup Guide

## Overview

This guide explains how to integrate NIJA's API Gateway with iOS and Android mobile applications. The API Gateway provides a clean, secure interface for controlling the NIJA trading bot from mobile devices.

**Status**: ✅ API Gateway Ready (v7.2 Strategy Locked)

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Mobile Apps (iOS/Android)                   │
│          React Native / Flutter / Native                 │
└────────────────────┬────────────────────────────────────┘
                     │ HTTPS/REST API
                     ▼
┌─────────────────────────────────────────────────────────┐
│              NIJA API Gateway                            │
│              (api_gateway.py)                            │
│                                                          │
│  Endpoints:                                              │
│  - POST   /api/v1/start       (Start trading)           │
│  - POST   /api/v1/stop        (Stop trading)            │
│  - GET    /api/v1/balance     (Get balance)             │
│  - GET    /api/v1/positions   (Get positions)           │
│  - GET    /api/v1/performance (Get metrics)             │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              User Control Backend                        │
│              (user_control.py)                           │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              NIJA Trading Engine                         │
│              (bot.py + v7.2 Strategy)                    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Exchanges (Coinbase, Kraken, etc.)          │
└─────────────────────────────────────────────────────────┘
```

## API Endpoints

### Base URL

```
Production: https://your-nija-deployment.railway.app
Development: http://localhost:8000
```

### Authentication

All API requests (except `/` and `/health`) require JWT authentication.

**Header Format:**
```
Authorization: Bearer <jwt_token>
```

### Available Endpoints

#### 1. **GET /** - API Information
Get basic API information and status.

**Request:**
```http
GET / HTTP/1.1
Host: your-nija-deployment.railway.app
```

**Response:**
```json
{
  "name": "NIJA Trading API Gateway",
  "version": "1.0.0",
  "strategy": "v7.2 (Locked - Profitability Mode)",
  "status": "operational",
  "docs": "/api/v1/docs"
}
```

#### 2. **GET /health** - Health Check
Check if the API is operational.

**Request:**
```http
GET /health HTTP/1.1
Host: your-nija-deployment.railway.app
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-01-27T22:23:53.510Z"
}
```

#### 3. **POST /api/v1/start** - Start Trading
Start the trading engine for the authenticated user.

**Request:**
```http
POST /api/v1/start HTTP/1.1
Host: your-nija-deployment.railway.app
Authorization: Bearer <jwt_token>
Content-Type: application/json

{}
```

**Response:**
```json
{
  "success": true,
  "message": "Trading engine started successfully",
  "status": "running",
  "timestamp": "2026-01-27T22:23:53.510Z"
}
```

**Error Response:**
```json
{
  "detail": "User not enabled or no permissions configured"
}
```

#### 4. **POST /api/v1/stop** - Stop Trading
Stop the trading engine for the authenticated user.

**Request:**
```http
POST /api/v1/stop HTTP/1.1
Host: your-nija-deployment.railway.app
Authorization: Bearer <jwt_token>
Content-Type: application/json

{}
```

**Response:**
```json
{
  "success": true,
  "message": "Trading engine stopped successfully",
  "status": "stopped",
  "timestamp": "2026-01-27T22:23:53.510Z"
}
```

#### 5. **GET /api/v1/balance** - Get Balance
Get current account balance for the authenticated user.

**Request:**
```http
GET /api/v1/balance HTTP/1.1
Host: your-nija-deployment.railway.app
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "success": true,
  "balance": 1250.50,
  "currency": "USD",
  "available_for_trading": 1187.97,
  "broker": "Coinbase",
  "timestamp": "2026-01-27T22:23:53.510Z"
}
```

#### 6. **GET /api/v1/positions** - Get Positions
Get all active positions for the authenticated user.

**Request:**
```http
GET /api/v1/positions HTTP/1.1
Host: your-nija-deployment.railway.app
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "success": true,
  "positions": [
    {
      "pair": "BTC-USD",
      "side": "long",
      "size": 0.05,
      "entry_price": 42500.00,
      "current_price": 43200.00,
      "unrealized_pnl": 35.00,
      "unrealized_pnl_percent": 1.65,
      "stop_loss": 41800.00,
      "take_profit": 44000.00,
      "opened_at": "2026-01-27T20:15:30.000Z"
    },
    {
      "pair": "ETH-USD",
      "side": "long",
      "size": 2.5,
      "entry_price": 2250.00,
      "current_price": 2280.00,
      "unrealized_pnl": 75.00,
      "unrealized_pnl_percent": 1.33,
      "stop_loss": 2200.00,
      "take_profit": 2350.00,
      "opened_at": "2026-01-27T21:00:15.000Z"
    }
  ],
  "total_positions": 2,
  "total_unrealized_pnl": 110.00,
  "timestamp": "2026-01-27T22:23:53.510Z"
}
```

#### 7. **GET /api/v1/performance** - Get Performance Metrics
Get trading performance metrics for the authenticated user.

**Request:**
```http
GET /api/v1/performance?period=all_time HTTP/1.1
Host: your-nija-deployment.railway.app
Authorization: Bearer <jwt_token>
```

**Query Parameters:**
- `period` (optional): `all_time`, `30d`, `7d`, `24h` (default: `all_time`)

**Response:**
```json
{
  "success": true,
  "metrics": {
    "total_trades": 150,
    "winning_trades": 98,
    "losing_trades": 52,
    "win_rate": 65.33,
    "total_pnl": 1250.75,
    "total_profit": 2100.50,
    "total_loss": -849.75,
    "average_win": 21.43,
    "average_loss": -16.34,
    "profit_factor": 2.47,
    "sharpe_ratio": null,
    "max_drawdown": null,
    "active_positions": 2
  },
  "period": "all_time",
  "timestamp": "2026-01-27T22:23:53.510Z"
}
```

## React Native Integration Example

### 1. Install Dependencies

```bash
npm install axios @react-native-async-storage/async-storage
```

### 2. Create API Client

Create a file `services/nijaApi.js`:

```javascript
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

// Configuration - use environment variable in production
// Example: Set REACT_APP_API_URL in your .env file
const BASE_URL = process.env.REACT_APP_API_URL || 'https://your-nija-deployment.railway.app';

class NijaApiClient {
  constructor() {
    this.client = axios.create({
      baseURL: BASE_URL,
      timeout: 10000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Add request interceptor for JWT token
    this.client.interceptors.request.use(
      async (config) => {
        const token = await AsyncStorage.getItem('jwt_token');
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );
  }

  // Start trading
  async startTrading() {
    try {
      const response = await this.client.post('/api/v1/start', {});
      return response.data;
    } catch (error) {
      throw this._handleError(error);
    }
  }

  // Stop trading
  async stopTrading() {
    try {
      const response = await this.client.post('/api/v1/stop', {});
      return response.data;
    } catch (error) {
      throw this._handleError(error);
    }
  }

  // Get balance
  async getBalance() {
    try {
      const response = await this.client.get('/api/v1/balance');
      return response.data;
    } catch (error) {
      throw this._handleError(error);
    }
  }

  // Get positions
  async getPositions() {
    try {
      const response = await this.client.get('/api/v1/positions');
      return response.data;
    } catch (error) {
      throw this._handleError(error);
    }
  }

  // Get performance
  async getPerformance(period = 'all_time') {
    try {
      const response = await this.client.get(`/api/v1/performance?period=${period}`);
      return response.data;
    } catch (error) {
      throw this._handleError(error);
    }
  }

  // Health check
  async healthCheck() {
    try {
      const response = await this.client.get('/health');
      return response.data;
    } catch (error) {
      throw this._handleError(error);
    }
  }

  _handleError(error) {
    if (error.response) {
      // Server responded with error
      return new Error(error.response.data.detail || 'API error');
    } else if (error.request) {
      // No response received
      return new Error('No response from server');
    } else {
      // Request setup error
      return new Error(error.message);
    }
  }
}

export default new NijaApiClient();
```

### 3. Example React Native Component

```javascript
import React, { useState, useEffect } from 'react';
import { View, Text, Button, StyleSheet, ActivityIndicator } from 'react-native';
import nijaApi from './services/nijaApi';

export default function TradingDashboard() {
  const [loading, setLoading] = useState(false);
  const [balance, setBalance] = useState(null);
  const [positions, setPositions] = useState([]);
  const [tradingStatus, setTradingStatus] = useState('stopped');

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const [balanceData, positionsData] = await Promise.all([
        nijaApi.getBalance(),
        nijaApi.getPositions(),
      ]);
      setBalance(balanceData);
      setPositions(positionsData.positions);
    } catch (error) {
      console.error('Error loading data:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleStartTrading = async () => {
    try {
      setLoading(true);
      const result = await nijaApi.startTrading();
      if (result.success) {
        setTradingStatus('running');
        alert('Trading started successfully!');
      }
    } catch (error) {
      alert(`Error: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleStopTrading = async () => {
    try {
      setLoading(true);
      const result = await nijaApi.stopTrading();
      if (result.success) {
        setTradingStatus('stopped');
        alert('Trading stopped successfully!');
      }
    } catch (error) {
      alert(`Error: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <ActivityIndicator size="large" color="#0000ff" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>NIJA Trading Dashboard</Text>

      {balance && (
        <View style={styles.balanceCard}>
          <Text style={styles.label}>Balance</Text>
          <Text style={styles.balanceValue}>
            ${balance.balance.toFixed(2)}
          </Text>
          <Text style={styles.subtext}>
            Available: ${balance.available_for_trading?.toFixed(2) || 'N/A'}
          </Text>
        </View>
      )}

      <View style={styles.controls}>
        <Button
          title="Start Trading"
          onPress={handleStartTrading}
          disabled={tradingStatus === 'running'}
          color="#28a745"
        />
        <View style={styles.spacer} />
        <Button
          title="Stop Trading"
          onPress={handleStopTrading}
          disabled={tradingStatus === 'stopped'}
          color="#dc3545"
        />
      </View>

      <View style={styles.positions}>
        <Text style={styles.sectionTitle}>
          Active Positions ({positions.length})
        </Text>
        {positions.map((position, index) => (
          <View key={index} style={styles.positionCard}>
            <Text style={styles.positionPair}>{position.pair}</Text>
            <Text>Size: {position.size}</Text>
            <Text>Entry: ${position.entry_price.toFixed(2)}</Text>
            <Text style={position.unrealized_pnl >= 0 ? styles.profit : styles.loss}>
              P&L: ${position.unrealized_pnl?.toFixed(2) || 'N/A'}
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 20,
    backgroundColor: '#f5f5f5',
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    marginBottom: 20,
    textAlign: 'center',
  },
  balanceCard: {
    backgroundColor: 'white',
    padding: 20,
    borderRadius: 10,
    marginBottom: 20,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 3,
  },
  label: {
    fontSize: 14,
    color: '#666',
    marginBottom: 5,
  },
  balanceValue: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#333',
  },
  subtext: {
    fontSize: 12,
    color: '#999',
    marginTop: 5,
  },
  controls: {
    flexDirection: 'row',
    marginBottom: 20,
  },
  spacer: {
    width: 10,
  },
  positions: {
    marginTop: 10,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    marginBottom: 10,
  },
  positionCard: {
    backgroundColor: 'white',
    padding: 15,
    borderRadius: 8,
    marginBottom: 10,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.1,
    shadowRadius: 2,
    elevation: 2,
  },
  positionPair: {
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 5,
  },
  profit: {
    color: '#28a745',
    fontWeight: 'bold',
  },
  loss: {
    color: '#dc3545',
    fontWeight: 'bold',
  },
});
```

## Flutter Integration Example

### 1. Add Dependencies to `pubspec.yaml`

```yaml
dependencies:
  http: ^1.1.0
  shared_preferences: ^2.2.2
```

### 2. Create API Client

Create a file `lib/services/nija_api.dart`:

```dart
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

// Configuration - use environment variable or app config in production
// You can pass this via build-time configuration or runtime config
class NijaApiClient {
  // Default to production URL, override via constructor
  final String baseUrl;

  NijaApiClient({
    this.baseUrl = 'https://your-nija-deployment.railway.app'
  });

  Future<Map<String, String>> _getHeaders() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString('jwt_token') ?? '';

    return {
      'Content-Type': 'application/json',
      if (token.isNotEmpty) 'Authorization': 'Bearer $token',
    };
  }

  Future<Map<String, dynamic>> startTrading() async {
    final headers = await _getHeaders();
    final response = await http.post(
      Uri.parse('$baseUrl/api/v1/start'),
      headers: headers,
      body: json.encode({}),
    );

    if (response.statusCode == 200) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to start trading: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> stopTrading() async {
    final headers = await _getHeaders();
    final response = await http.post(
      Uri.parse('$baseUrl/api/v1/stop'),
      headers: headers,
      body: json.encode({}),
    );

    if (response.statusCode == 200) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to stop trading: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> getBalance() async {
    final headers = await _getHeaders();
    final response = await http.get(
      Uri.parse('$baseUrl/api/v1/balance'),
      headers: headers,
    );

    if (response.statusCode == 200) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to get balance: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> getPositions() async {
    final headers = await _getHeaders();
    final response = await http.get(
      Uri.parse('$baseUrl/api/v1/positions'),
      headers: headers,
    );

    if (response.statusCode == 200) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to get positions: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> getPerformance({String period = 'all_time'}) async {
    final headers = await _getHeaders();
    final response = await http.get(
      Uri.parse('$baseUrl/api/v1/performance?period=$period'),
      headers: headers,
    );

    if (response.statusCode == 200) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to get performance: ${response.body}');
    }
  }
}
```

## Deployment

### Option 1: Deploy with Main Bot (Same Server)

Add to your start script or create a new deployment configuration:

```bash
# Start API Gateway
python api_gateway.py &

# Start main bot
python bot.py
```

### Option 2: Deploy Separately (Microservices)

Deploy the API Gateway as a separate service:

```bash
# Install dependencies
pip install fastapi uvicorn pyjwt

# Run API Gateway
python api_gateway.py
```

### Environment Variables

```bash
# Required
JWT_SECRET_KEY=your-secret-key-here

# Optional
JWT_EXPIRATION_HOURS=24
PORT=8000
```

## Security Considerations

1. **HTTPS Only**: Always use HTTPS in production
2. **JWT Secrets**: Use strong, random JWT secret keys
3. **CORS**: Configure allowed origins properly
4. **Rate Limiting**: Add rate limiting for production (recommended: 100 req/min per user)
5. **Input Validation**: All inputs are validated via Pydantic models
6. **Authentication**: JWT tokens expire after 24 hours (configurable)

## Next Steps

1. ✅ API Gateway created (`api_gateway.py`)
2. ✅ Documentation created (this file)
3. 🔄 **Deploy API Gateway** (add to Railway/Render deployment)
4. 🔄 **Create JWT authentication flow** (login/signup endpoints)
5. 🔄 **Build React Native app** (using examples above)
6. 🔄 **Build iOS app** (submit to App Store)
7. 🔄 **Build Android app** (submit to Play Store)

## Support

For issues or questions:
- Check API documentation: `/api/v1/docs`
- Review logs for error details
- Ensure JWT token is valid and not expired
- Verify user has proper permissions configured

---

**Version**: 1.0.0
**Strategy**: v7.2 (Locked - Profitability Mode)
**Last Updated**: January 27, 2026
