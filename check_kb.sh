#!/bin/bash
mysql -u root -e 'SELECT id, name, access_level, is_active FROM dermaintegrate.rag_knowledge_bases ORDER BY id;' 2>/dev/null
if [ $? -ne 0 ]; then
  mysql -e 'SELECT id, name, access_level, is_active FROM dermaintegrate.rag_knowledge_bases ORDER BY id;'
fi
