const dotenv = require('dotenv');

// 加载 .env 配置
dotenv.config();

const config = {
  port: process.env.PORT || 3000,
  aiBaseUrl: process.env.AI_BASE_URL || 'http://124.222.0.186/ai'
};

// 启动时打印配置，便于调试
console.log('Config loaded:', {
  port: config.port,
  aiBaseUrl: config.aiBaseUrl
});

module.exports = config;