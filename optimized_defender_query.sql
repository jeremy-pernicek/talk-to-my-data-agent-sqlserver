-- Optimized Query: Find defenders outperforming their contracts who will be free agents
-- This query directly fetches only the necessary data to avoid timeouts

WITH CurrentSeason AS (
    -- Get the current season (2024-25 assumed)
    SELECT 2024 AS SeasonYear
),
DefenderContracts AS (
    -- Get defenders with their current contract details
    SELECT DISTINCT
        p.PlayerId,
        p.NHLId,
        p.Firstname,
        p.LastName,
        p.Position,
        tps.TeamId,
        t.Name AS TeamName,
        tps.CapHitAug AS CurrentCapHit,
        tps.ContractStatus,
        tps.ContractExpiry,
        -- Performance metrics from team player summary
        tps.Age,
        tps.GP AS GamesPlayed,
        tps.G AS Goals,
        tps.A AS Assists,
        tps.PTS AS Points,
        tps.PlusMinus
    FROM [PuckPedia].[vwPlayers] p
    INNER JOIN [PuckPedia].[vwTeamPlayerSummary] tps
        ON p.PlayerId = tps.NHLPlayerId
    INNER JOIN [PuckPedia].[vwTeams] t
        ON tps.TeamId = t.TeamId
    WHERE 
        p.Position IN ('Defense', 'D')  -- Only defenders
        AND tps.ContractStatus IN ('UFA', 'RFA')  -- Will be free agents
        AND tps.ContractExpiry = 2025  -- Contract expires at end of current season
        AND tps.CapHitAug > 0  -- Has a current contract
),
PerformanceMetrics AS (
    -- Calculate performance relative to contract value
    SELECT 
        *,
        -- Points per million of cap hit (higher = better value)
        CASE 
            WHEN CurrentCapHit > 0 THEN Points / (CurrentCapHit / 1000000.0)
            ELSE 0 
        END AS PointsPerMillion,
        -- Determine if outperforming (simplified metric)
        CASE 
            WHEN Points >= 30 AND CurrentCapHit < 5000000 THEN 'Excellent Value'
            WHEN Points >= 20 AND CurrentCapHit < 3000000 THEN 'Great Value'
            WHEN Points > (CurrentCapHit / 200000.0) THEN 'Good Value'
            ELSE 'Average/Below'
        END AS PerformanceValue
    FROM DefenderContracts
)
-- Final result: Top defenders outperforming their contracts
SELECT TOP 20
    Firstname + ' ' + LastName AS PlayerName,
    TeamName,
    Position,
    ContractStatus AS FAStatus,
    FORMAT(CurrentCapHit, 'C0') AS CapHit,
    Age,
    GamesPlayed,
    Goals,
    Assists,
    Points,
    PlusMinus,
    ROUND(PointsPerMillion, 2) AS PtsPerMillion,
    PerformanceValue
FROM PerformanceMetrics
WHERE PerformanceValue != 'Average/Below'  -- Only outperformers
ORDER BY PointsPerMillion DESC, Points DESC;

-- Alternative simpler version if the above times out:
/*
SELECT TOP 20
    p.Firstname + ' ' + p.LastName AS PlayerName,
    t.Name AS TeamName,
    tps.ContractStatus,
    tps.CapHitAug AS CapHit,
    tps.Age,
    tps.PTS AS Points,
    ROUND(tps.PTS / (tps.CapHitAug / 1000000.0), 2) AS PointsPerMillion
FROM [PuckPedia].[vwPlayers] p
INNER JOIN [PuckPedia].[vwTeamPlayerSummary] tps ON p.PlayerId = tps.NHLPlayerId
INNER JOIN [PuckPedia].[vwTeams] t ON tps.TeamId = t.TeamId
WHERE 
    p.Position = 'Defense'
    AND tps.ContractStatus IN ('UFA', 'RFA')
    AND tps.ContractExpiry = 2025
    AND tps.CapHitAug > 0
    AND tps.PTS > 15  -- Basic performance filter
ORDER BY tps.PTS / (tps.CapHitAug / 1000000.0) DESC;
*/