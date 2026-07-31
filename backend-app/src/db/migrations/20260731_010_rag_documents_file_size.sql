-- Add file_size column to rag_documents
-- NULL for historical records; populated from multer file.size on new uploads
ALTER TABLE rag_documents ADD COLUMN file_size BIGINT DEFAULT NULL;
