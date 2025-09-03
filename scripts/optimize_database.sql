-- Performance optimization indexes for LeadChatbot
-- Run these on your database to improve query performance

-- Chat-related indexes
CREATE INDEX IF NOT EXISTS idx_chat_sessions_client_session 
ON chat_sessions(client_id, session_id);

CREATE INDEX IF NOT EXISTS idx_chat_history_session_timestamp 
ON chat_history(session_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_chat_history_session_sender 
ON chat_history(session_id, sender);

-- Lead-related indexes  
CREATE INDEX IF NOT EXISTS idx_leads_client_email 
ON leads(client_id, email) WHERE email IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_client_phone 
ON leads(client_id, phone_number) WHERE phone_number IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_client_status 
ON leads(client_id, status);

CREATE INDEX IF NOT EXISTS idx_leads_browser_session 
ON leads(client_id, browser_session_id) WHERE browser_session_id IS NOT NULL;

-- Deployment-related indexes
CREATE INDEX IF NOT EXISTS idx_deployments_custom_client_deployed 
ON client_deployments(custom_client_id, is_deployed) WHERE is_deployed = true;

-- Knowledge base indexes
CREATE INDEX IF NOT EXISTS idx_knowledge_docs_client 
ON knowledge_documents(client_id);

-- Vector store indexes (for Supabase documents table)
CREATE INDEX IF NOT EXISTS idx_documents_collection 
ON documents USING GIN ((metadata->>'collection'));

-- Analytics indexes
CREATE INDEX IF NOT EXISTS idx_analytics_client_date 
ON analytics_daily(client_id, date DESC);

-- Sequence/automation indexes
CREATE INDEX IF NOT EXISTS idx_sequence_states_next_send 
ON lead_sequence_states(status, next_send_time) 
WHERE status = 'ACTIVE';

-- Composite indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_leads_client_contact_info 
ON leads(client_id, email, phone_number, status);

CREATE INDEX IF NOT EXISTS idx_sessions_client_lead 
ON chat_sessions(client_id, lead_id, session_id);
