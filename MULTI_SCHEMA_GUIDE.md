# Multi-Schema Support Guide

This guide explains how to configure and use the Talk-to-My-Data application with multiple SQL Server schemas.

## Configuration

### Single Schema (Backward Compatible)

```bash
# Traditional single schema configuration
AZURE_SQL_SCHEMA=dbo
```

### Multiple Schemas

```bash
# New multi-schema configuration
AZURE_SQL_SCHEMAS=dbo,hr,finance,inventory,sales
```

You can use either `AZURE_SQL_SCHEMA` or `AZURE_SQL_SCHEMAS`, but not both. If `AZURE_SQL_SCHEMAS` is provided, it takes precedence.

## Environment Variable Examples

### Example 1: HR and Finance Departments
```bash
AZURE_SQL_HOST=your-server.database.windows.net
AZURE_SQL_PORT=1433
AZURE_SQL_USER=your-username
AZURE_SQL_PASSWORD=your-password
AZURE_SQL_DATABASE=YourDatabase
AZURE_SQL_SCHEMAS=hr,finance
```

### Example 2: Complete Business System
```bash
AZURE_SQL_SCHEMAS=dbo,sales,inventory,accounting,hr,customer_service
```

## How It Works

### Table Listing
- **Single Schema**: Tables appear as `employees`, `customers`, etc.
- **Multiple Schemas**: Tables appear as `hr.employees`, `finance.budgets`, `sales.orders`, etc.

### Query Generation
The LLM automatically handles schema-qualified table names:

```sql
-- Single schema query
SELECT * FROM employees WHERE department = 'IT'

-- Multi-schema query
SELECT 
    e.name,
    s.total_sales
FROM hr.employees e
JOIN sales.sales_summary s ON e.employee_id = s.employee_id
```

### Data Dictionary
Each table's data dictionary includes the schema information, helping the LLM understand which schema each table belongs to.

## Use Cases

### 1. Departmental Analysis
Configure schemas for different departments:
- `hr` - Employee data, payroll, benefits
- `finance` - Budgets, expenses, financial reports  
- `sales` - Orders, customers, sales performance
- `inventory` - Stock levels, products, suppliers

### 2. Multi-Tenant Applications
Configure schemas for different clients or business units:
- `client_a` - Data for Client A
- `client_b` - Data for Client B
- `shared` - Common reference data

### 3. Development Environments
Configure schemas for different data stages:
- `prod` - Production data
- `staging` - Staging environment data
- `dev` - Development data

## Business Question Examples

With multi-schema support, you can ask questions that span multiple business areas:

### Cross-Departmental Questions
- "Show me sales performance by employee department"
- "What's the total cost of inventory for items sold last quarter?"
- "Which HR policies correlate with sales performance?"

### Financial Analysis
- "Compare actual expenses vs budget across all departments"
- "Show cash flow impact of inventory purchases"
- "What are our top expenses by department and category?"

### Operational Insights
- "Which departments have the highest employee turnover?"
- "How do inventory levels affect sales fulfillment rates?"
- "Show customer satisfaction scores by sales region and support team"

## Schema Selection in UI

When using the application:

1. **Data Selection**: You'll see tables grouped by schema
2. **Table Names**: Schema-qualified names like `hr.employees`, `sales.orders`
3. **Relationships**: The system can detect relationships across schemas
4. **Queries**: Generated SQL automatically uses proper schema qualification

## Best Practices

### 1. Schema Naming
- Use descriptive schema names that match business functions
- Avoid special characters (stick to alphanumeric, underscore, dot)
- Keep names short but meaningful

### 2. Security Considerations
- Ensure the SQL Server user has appropriate permissions on all schemas
- Consider using database roles for schema access management
- Test permissions thoroughly before deployment

### 3. Performance
- Multi-schema queries may be more complex
- Ensure proper indexing across schemas for related tables
- Monitor query performance with multiple schemas

### 4. Documentation
- Document which schemas contain which types of data
- Maintain a schema-to-business-function mapping
- Update documentation when adding new schemas

## Troubleshooting

### Common Issues

1. **Tables not appearing**: Check user permissions on all configured schemas
2. **Schema qualification errors**: Verify schema names are spelled correctly
3. **Query performance**: Ensure indexes exist for cross-schema joins

### Testing Configuration

Use the test script to verify your configuration:

```bash
python test_multischema.py
```

### Checking Permissions

Verify the user has access to all schemas:

```sql
SELECT 
    s.name AS schema_name,
    p.permission_name,
    p.state_desc
FROM sys.schemas s
LEFT JOIN sys.database_permissions p ON s.schema_id = p.major_id
WHERE s.name IN ('dbo', 'hr', 'finance', 'sales', 'inventory')
ORDER BY s.name, p.permission_name;
```

## Migration Guide

### From Single to Multi-Schema

1. **Backup Configuration**: Save your current `.env` file
2. **Update Environment Variables**:
   ```bash
   # Old
   AZURE_SQL_SCHEMA=dbo
   
   # New
   AZURE_SQL_SCHEMAS=dbo,hr,finance
   ```
3. **Test Connection**: Verify table listing works
4. **Update Documentation**: Note which schemas contain which data
5. **Train Users**: Explain new schema-qualified table names

### Rollback Plan

To rollback to single schema:
1. Remove `AZURE_SQL_SCHEMAS` from environment
2. Set `AZURE_SQL_SCHEMA=dbo` (or your preferred schema)
3. Restart the application

## Support

For issues with multi-schema support:
1. Check the application logs for schema-related errors
2. Verify SQL Server permissions using the queries above
3. Test with the provided test script
4. Review this documentation for configuration examples