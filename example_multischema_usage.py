#!/usr/bin/env python3
"""
Example usage of multi-schema support in Talk-to-My-Data
"""

import os

def demonstrate_environment_config():
    """Show different ways to configure schemas"""
    print("Multi-Schema Configuration Examples")
    print("="*50)
    
    print("\n1. Single Schema (Traditional)")
    print("   AZURE_SQL_SCHEMA=dbo")
    
    print("\n2. Multiple Schemas - Department Focus")
    print("   AZURE_SQL_SCHEMAS=hr,finance,sales")
    
    print("\n3. Multiple Schemas - Complete Business")
    print("   AZURE_SQL_SCHEMAS=dbo,hr,finance,sales,inventory,customer_service")
    
    print("\n4. Multi-Tenant Configuration")
    print("   AZURE_SQL_SCHEMAS=client_a,client_b,shared_data")

def demonstrate_table_naming():
    """Show how table names appear in different configurations"""
    print("\n\nTable Naming Examples")
    print("="*50)
    
    configurations = [
        ("Single Schema (dbo)", ["dbo"], [
            "employees", "customers", "orders", "products"
        ]),
        ("Single Schema (hr)", ["hr"], [
            "hr.employees", "hr.departments", "hr.payroll"
        ]),
        ("Multiple Schemas", ["dbo", "hr", "finance"], [
            "customers", "hr.employees", "hr.departments", 
            "finance.budgets", "finance.expenses", "dbo.audit_log"
        ])
    ]
    
    for config_name, schemas, table_examples in configurations:
        print(f"\n{config_name}:")
        print(f"  Schemas: {schemas}")
        print(f"  Table Names:")
        for table in table_examples:
            print(f"    - {table}")

def demonstrate_business_questions():
    """Show example business questions for multi-schema setup"""
    print("\n\nBusiness Question Examples")
    print("="*50)
    
    questions = [
        {
            "category": "Cross-Departmental Analysis",
            "questions": [
                "Show me sales performance by employee department",
                "Which departments have the highest overtime costs?",
                "What's the correlation between HR training and sales performance?"
            ]
        },
        {
            "category": "Financial Analysis", 
            "questions": [
                "Compare actual expenses vs budget across all departments",
                "What are our top 5 expense categories this month?",
                "Show cash flow impact of inventory purchases"
            ]
        },
        {
            "category": "Operational Insights",
            "questions": [
                "Which products are below reorder points?",
                "Show customer satisfaction by sales region and support team",
                "What are the top 3 bottlenecks in our operations?"
            ]
        },
        {
            "category": "Inventory & Sales",
            "questions": [
                "Show items that are below their reorder point",
                "Generate inventory turnover report for last quarter",
                "List top 10 customers by revenue"
            ]
        }
    ]
    
    for category_info in questions:
        print(f"\n{category_info['category']}:")
        for question in category_info['questions']:
            print(f"  • {question}")

def demonstrate_sql_examples():
    """Show SQL query examples with multi-schema"""
    print("\n\nSQL Query Examples")
    print("="*50)
    
    examples = [
        {
            "description": "Cross-schema employee and sales analysis",
            "sql": """
SELECT 
    e.first_name + ' ' + e.last_name AS employee_name,
    e.department,
    s.total_sales,
    s.commission
FROM hr.employees e
LEFT JOIN sales.employee_sales s ON e.employee_id = s.employee_id
WHERE e.active = 1
ORDER BY s.total_sales DESC
"""
        },
        {
            "description": "Financial summary across departments",
            "sql": """
SELECT 
    d.department_name,
    f.budget_amount,
    f.actual_spent,
    (f.actual_spent - f.budget_amount) AS variance
FROM hr.departments d
JOIN finance.department_budgets f ON d.department_id = f.department_id
WHERE f.fiscal_year = 2024
ORDER BY variance DESC
"""
        },
        {
            "description": "Inventory and sales correlation",
            "sql": """
SELECT 
    p.product_name,
    i.current_stock,
    i.reorder_point,
    s.units_sold_last_month
FROM inventory.products p
JOIN inventory.stock_levels i ON p.product_id = i.product_id  
JOIN sales.product_sales s ON p.product_id = s.product_id
WHERE i.current_stock < i.reorder_point
ORDER BY s.units_sold_last_month DESC
"""
        }
    ]
    
    for i, example in enumerate(examples, 1):
        print(f"\n{i}. {example['description']}:")
        print(example['sql'].strip())

def main():
    """Run all demonstrations"""
    print("Talk-to-My-Data: Multi-Schema Support Examples")
    print("=" * 80)
    
    demonstrate_environment_config()
    demonstrate_table_naming() 
    demonstrate_business_questions()
    demonstrate_sql_examples()
    
    print("\n\nGetting Started")
    print("="*50)
    print("1. Update your .env file with AZURE_SQL_SCHEMAS")
    print("2. Restart your Talk-to-My-Data application")
    print("3. Select tables from multiple schemas")
    print("4. Ask questions that span business domains")
    print("\nFor detailed setup instructions, see MULTI_SCHEMA_GUIDE.md")

if __name__ == "__main__":
    main()