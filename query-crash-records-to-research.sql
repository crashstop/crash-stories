-- simple query to
WITH
Records AS (
    SELECT
        crash_record_id
        , 'crash '
            || CASE STRFTIME('%m', crash_date)
                WHEN '01' THEN 'January'
                WHEN '02' THEN 'February'
                WHEN '03' THEN 'March'
                WHEN '04' THEN 'April'
                WHEN '05' THEN 'May'
                WHEN '06' THEN 'June'
                WHEN '07' THEN 'July'
                WHEN '08' THEN 'August'
                WHEN '09' THEN 'September'
                WHEN '10' THEN 'October'
                WHEN '11' THEN 'November'
                WHEN '12' THEN 'December'
                END
            || ' '
            || STRFTIME('%d, %Y', crash_date) || ' chicago ' || address || ' '
            || REPLACE(neighborhood_id, '-', ' ')
            AS query
        , crash_date
        , injuries_total
        , CASE
            WHEN fatal_pedestrian_tally > 0  THEN 'fatal pedestrian'
            WHEN fatal_cyclist_tally    > 0  THEN 'fatal cyclist'
            WHEN fatal_tally            > 0  THEN 'fatal'
            WHEN incap_pedestrian_tally > 0  THEN 'incap pedestrian'
            WHEN incap_cyclist_tally    > 0  THEN 'incap cyclist'
            WHEN incap_tally            > 3  THEN 'incap mass'
            WHEN incap_tally            > 0  THEN 'incap'
            WHEN injuries_total         > 4  THEN 'injury mass'
          END AS severe_cat
        , neighborhood_id
        , address
        , category
        , crash_type

    FROM
        crashes_serving
    ORDER BY
        crash_date DESC
)

SELECT
    *
FROM
    Records
WHERE
    1 = 1
    AND severe_cat IS NOT NULL
    -- AND SUBSTR(crash_date,1, 10) = '2024-09-18'
    AND crash_date BETWEEN '2026-05-01' AND '2026-07-01'
