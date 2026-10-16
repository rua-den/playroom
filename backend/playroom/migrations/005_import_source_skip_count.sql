-- Preserve source omissions for durable review. NULL means this legacy row
-- predates the count and must be shown as unknown.
ALTER TABLE chatgpt_import_sources ADD COLUMN skipped_messages INTEGER;
