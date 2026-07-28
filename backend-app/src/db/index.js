const appPool  = require('./pools/app');
const hisPool  = require('./pools/his');
const lisPool  = require('./pools/lis');
const pacsPool = require('./pools/pacs');

// 向下兼容：旧代码 require('./db') 直接使用的 pool 指向 appPool
module.exports = appPool;
module.exports.appPool  = appPool;
module.exports.hisPool  = hisPool;
module.exports.lisPool  = lisPool;
module.exports.pacsPool = pacsPool;
