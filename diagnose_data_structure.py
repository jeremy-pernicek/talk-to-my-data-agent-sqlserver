#!/usr/bin/env python3
"""
Diagnostic script to understand the actual data structure in the SQL Server database
This will help us build working queries that return actual data
"""

import sys
import time

# Add the project path to sys.path
sys.path.insert(0, '/Users/jeremy.pernicek/Desktop/aug_sql_integration/talk-to-my-data-agent-merged')

def create_diagnostic_queries():
    """Create a series of diagnostic queries to understand the data"""
    
    diagnostic_queries = []
    
    # First, let's understand what data exists in key tables
    diagnostic_queries.append({
        "name": "Sample Player Data",
        "description": "Get sample players to understand the Position column values",
        "query": """
        SELECT TOP 10 
            PlayerId, 
            Firstname, 
            LastName, 
            Position,
            BirthDate
        FROM [PuckPedia].[vwPlayers]
        WHERE Position IS NOT NULL
        ORDER BY PlayerId;
        """
    })
    
    diagnostic_queries.append({
        "name": "Position Values Analysis", 
        "description": "See what Position values actually exist",
        "query": """
        SELECT DISTINCT Position, COUNT(*) as PlayerCount
        FROM [PuckPedia].[vwPlayers]
        WHERE Position IS NOT NULL
        GROUP BY Position
        ORDER BY PlayerCount DESC;
        """
    })
    
    diagnostic_queries.append({
        "name": "Team Player Summary Structure",
        "description": "Understand the vwTeamPlayerSummary table structure",
        "query": """
        SELECT TOP 5
            NHLPlayerId,
            TeamId,
            CapHitAug,
            ContractStatus,
            ContractExpiry,
            PTS,
            GP,
            G,
            A
        FROM [PuckPedia].[vwTeamPlayerSummary]
        WHERE CapHitAug > 0
        ORDER BY CapHitAug DESC;
        """
    })
    
    diagnostic_queries.append({
        "name": "Contract Status Values",
        "description": "See what ContractStatus values exist",
        "query": """
        SELECT DISTINCT ContractStatus, COUNT(*) as Count
        FROM [PuckPedia].[vwTeamPlayerSummary]
        WHERE ContractStatus IS NOT NULL
        GROUP BY ContractStatus
        ORDER BY Count DESC;
        """
    })
    
    diagnostic_queries.append({
        "name": "Contract Expiry Analysis",
        "description": "Understand contract expiry years",
        "query": """
        SELECT DISTINCT ContractExpiry, COUNT(*) as Count
        FROM [PuckPedia].[vwTeamPlayerSummary]
        WHERE ContractExpiry IS NOT NULL
        GROUP BY ContractExpiry
        ORDER BY ContractExpiry DESC;
        """
    })
    
    diagnostic_queries.append({
        "name": "Test Defender Query (Relaxed)",
        "description": "Try to find defenders with relaxed criteria",
        "query": """
        SELECT TOP 10
            p.Firstname + ' ' + p.LastName AS PlayerName,
            p.Position,
            tps.ContractStatus,
            tps.ContractExpiry,
            tps.CapHitAug,
            tps.PTS
        FROM [PuckPedia].[vwPlayers] p
        INNER JOIN [PuckPedia].[vwTeamPlayerSummary] tps 
            ON p.PlayerId = tps.NHLPlayerId
        WHERE p.Position LIKE '%D%'  -- More flexible position matching
            AND tps.CapHitAug > 0
            AND tps.PTS > 0
        ORDER BY tps.PTS DESC;
        """
    })
    
    diagnostic_queries.append({
        "name": "Find Any Free Agents",
        "description": "See if we have any players with UFA/RFA status",
        "query": """
        SELECT TOP 10
            p.Firstname + ' ' + p.LastName AS PlayerName,
            p.Position,
            tps.ContractStatus,
            tps.CapHitAug,
            tps.PTS
        FROM [PuckPedia].[vwPlayers] p
        INNER JOIN [PuckPedia].[vwTeamPlayerSummary] tps 
            ON p.PlayerId = tps.NHLPlayerId
        WHERE tps.ContractStatus IN ('UFA', 'RFA')
        ORDER BY tps.PTS DESC;
        """
    })
    
    return diagnostic_queries

def create_working_defender_query():
    """Create a working query for defenders that should return data"""
    
    return """
    -- Working query: Find defenders with good performance relative to cap hit
    -- This uses more flexible criteria to ensure we get results
    
    SELECT TOP 20
        p.Firstname + ' ' + p.LastName AS PlayerName,
        t.Name AS TeamName,
        p.Position,
        COALESCE(tps.ContractStatus, 'Unknown') AS FreeAgentStatus,
        COALESCE(tps.ContractExpiry, 0) AS ContractExpiry,
        FORMAT(tps.CapHitAug, 'C0') AS CapHit,
        tps.Age,
        tps.GP AS GamesPlayed,
        tps.G AS Goals,
        tps.A AS Assists, 
        tps.PTS AS Points,
        -- Calculate performance metrics
        CASE 
            WHEN tps.CapHitAug > 0 
            THEN ROUND(tps.PTS / (tps.CapHitAug / 1000000.0), 2)
            ELSE 0 
        END AS PointsPerMillion,
        
        -- Simple performance rating
        CASE 
            WHEN tps.PTS >= 40 THEN 'Elite'
            WHEN tps.PTS >= 25 THEN 'Very Good'  
            WHEN tps.PTS >= 15 THEN 'Good'
            WHEN tps.PTS >= 5 THEN 'Average'
            ELSE 'Below Average'
        END AS PerformanceLevel
        
    FROM [PuckPedia].[vwPlayers] p
    INNER JOIN [PuckPedia].[vwTeamPlayerSummary] tps 
        ON p.PlayerId = tps.NHLPlayerId
    INNER JOIN [PuckPedia].[vwTeams] t 
        ON tps.TeamId = t.TeamId
    WHERE 
        (p.Position LIKE '%D%' OR p.Position = 'Defense' OR p.Position = 'Defenseman') -- Flexible defender matching
        AND tps.CapHitAug > 500000  -- Has meaningful contract (> $500K)
        AND tps.GP > 10  -- Played meaningful games
        AND tps.PTS >= 0  -- Has point data
    ORDER BY 
        CASE 
            WHEN tps.CapHitAug > 0 
            THEN tps.PTS / (tps.CapHitAug / 1000000.0)
            ELSE 0 
        END DESC,
        tps.PTS DESC;
    """

def main():
    print("DIAGNOSTIC ANALYSIS: SQL Server Data Structure Investigation")
    print("=" * 70)
    print("Issue: Query returns 0 rows - need to understand actual data structure")
    print("=" * 70)
    
    # Generate diagnostic queries
    diagnostics = create_diagnostic_queries()
    
    print("\n🔍 DIAGNOSTIC QUERIES TO RUN:")
    print("-" * 50)
    
    for i, query_info in enumerate(diagnostics, 1):
        print(f"\n{i}. {query_info['name']}")
        print(f"   Purpose: {query_info['description']}")
        print("   Query:")
        # Show first few lines of query
        query_lines = query_info['query'].strip().split('\n')
        for line in query_lines[:3]:
            print(f"   {line.strip()}")
        if len(query_lines) > 3:
            print("   ...")
        print()
    
    print("\n🎯 CORRECTED WORKING QUERY:")
    print("-" * 50)
    working_query = create_working_defender_query()
    print(working_query)
    
    print("\n📋 RECOMMENDED INVESTIGATION STEPS:")
    print("-" * 50)
    print("1. Run the diagnostic queries above to understand:")
    print("   - What Position values exist (Defense? D? Defenseman?)")
    print("   - What ContractStatus values exist (UFA? RFA? Free Agent?)")  
    print("   - What ContractExpiry values exist (2024? 2025? Different format?)")
    print("   - Sample data to verify column names and JOINs")
    
    print("\n2. Common issues that cause 0 rows:")
    print("   - Wrong Position values ('Defense' vs 'D' vs 'Defenseman')")
    print("   - Wrong ContractStatus values ('UFA' vs 'Free Agent')")
    print("   - Wrong ContractExpiry format (2025 vs '2024-25' vs different)")
    print("   - Incorrect JOIN conditions (PlayerId vs NHLPlayerId)")
    print("   - Missing or NULL data in critical columns")
    
    print("\n3. The working query above uses:")
    print("   - Flexible Position matching: LIKE '%D%'")
    print("   - Lower thresholds: CapHitAug > 500000, GP > 10")
    print("   - COALESCE for potentially NULL columns")
    print("   - Multiple Position variations in WHERE clause")
    
    print("\n✅ NEXT STEPS:")
    print("-" * 50)
    print("1. Test the diagnostic queries to understand data structure")
    print("2. Update the SQL Server prompt with correct column values")
    print("3. Use flexible matching instead of exact values")
    print("4. Add data exploration guidance to prompts")

if __name__ == "__main__":
    main()