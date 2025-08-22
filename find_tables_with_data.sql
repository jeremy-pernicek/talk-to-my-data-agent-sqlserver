-- SQL Server query to find tables with data
-- Run this in your SQL Server to identify tables that have rows

SELECT 
    s.name AS SchemaName,
    t.name AS TableName,
    p.rows AS RowCount
FROM 
    sys.tables t
    INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
    INNER JOIN sys.partitions p ON t.object_id = p.object_id
WHERE 
    p.index_id IN (0, 1)  -- Heap or clustered index
    AND p.rows > 0  -- Only show tables with data
    AND s.name = 'dbo'  -- Focus on dbo schema
ORDER BY 
    p.rows DESC  -- Largest tables first