-- Add clarifications column to issues table
-- This stores clarifying questions and answers from the fix clarify phase

ALTER TABLE issues ADD COLUMN clarifications JSON;
