-- 普通业务总库 v1；公开字段位序由编解码器固定。
CREATE TABLE storage_instances (
    instance TEXT PRIMARY KEY NOT NULL
) STRICT;

CREATE TABLE storage_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    source_digest TEXT NOT NULL
) STRICT;

CREATE TABLE resource_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    ts TEXT NOT NULL,
    oil INTEGER,
    coin INTEGER,
    gem INTEGER,
    pt INTEGER,
    cube INTEGER,
    core INTEGER,
    medal INTEGER,
    merit INTEGER,
    guild_coin INTEGER,
    action_point INTEGER,
    yellow_coin INTEGER,
    purple_coin INTEGER
) STRICT;

CREATE TABLE resource_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    ts TEXT NOT NULL,
    resource TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK(amount<>0),
    task TEXT NOT NULL,
    operation TEXT NOT NULL,
    evidence TEXT NOT NULL,
    run_id TEXT,
    event_key TEXT NOT NULL,
    UNIQUE(instance,event_key,resource)
) STRICT;

CREATE TABLE resource_balances (
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    resource TEXT NOT NULL,
    value INTEGER NOT NULL,
    ts TEXT NOT NULL,
    run_id TEXT,
    cursor INTEGER NOT NULL,
    PRIMARY KEY(instance,resource)
) STRICT;

CREATE TABLE opsi_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imgid TEXT NOT NULL,
    instance TEXT REFERENCES storage_instances(instance),
    device_id TEXT,
    genre TEXT,
    server TEXT,
    zone TEXT,
    zone_type TEXT,
    zone_id INTEGER,
    hazard_level INTEGER,
    item TEXT,
    amount INTEGER,
    tag TEXT,
    combat_count INTEGER,
    created_at INTEGER
) STRICT;

CREATE TABLE storage_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    server TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    pages INTEGER NOT NULL CHECK(pages>0),
    catalog_version TEXT NOT NULL
) STRICT;

CREATE TABLE storage_items (
    scan_id INTEGER NOT NULL REFERENCES storage_scans(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    name TEXT NOT NULL,
    item_group TEXT NOT NULL,
    amount INTEGER CHECK(amount IS NULL OR amount>0),
    PRIMARY KEY(scan_id,item_id)
) STRICT;

CREATE TABLE cl1_months (
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    month TEXT NOT NULL,
    battle_count INTEGER,
    akashi_encounters INTEGER,
    akashi_ap INTEGER,
    meow_battle_raw_count INTEGER,
    meow_effective_rounds REAL,
    coins_history_version INTEGER,
    coins_cleanup_version INTEGER,
    last_ap_notification_ts TEXT,
    last_ap_notification_value INTEGER,
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    last_ap_notification_mask INTEGER NOT NULL DEFAULT 0 CHECK(last_ap_notification_mask BETWEEN 0 AND 3),
    siren_fields_mask INTEGER NOT NULL DEFAULT 0 CHECK(siren_fields_mask BETWEEN 0 AND 3),
    PRIMARY KEY(instance,month),
    CHECK(meow_effective_rounds IS NULL OR meow_effective_rounds BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE TABLE meow_hazard_counters (
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    hazard_level INTEGER NOT NULL CHECK(hazard_level BETWEEN 2 AND 6),
    battle_raw_count INTEGER,
    effective_rounds REAL,
    akashi_encounters INTEGER,
    akashi_ap INTEGER,
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    PRIMARY KEY(instance,month,hazard_level),
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month),
    CHECK(effective_rounds IS NULL OR effective_rounds BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE TABLE meow_duration_samples (
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('battle','round')),
    bucket INTEGER NOT NULL CHECK(bucket=0 OR bucket BETWEEN 2 AND 6),
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    duration_seconds REAL,
    observed_hazard INTEGER,
    entry_format TEXT NOT NULL CHECK(entry_format IN ('number','object','value')),
    hazard_present INTEGER NOT NULL CHECK(hazard_present IN (0,1)),
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    PRIMARY KEY(instance,month,kind,bucket,ordinal),
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month),
    CHECK(duration_seconds IS NULL OR duration_seconds BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE TABLE akashi_ap_purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    ts TEXT,
    amount INTEGER,
    base INTEGER,
    purchase_count INTEGER,
    source TEXT,
    entry_kind TEXT NOT NULL DEFAULT 'record' CHECK(entry_kind IN ('record','value')),
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    UNIQUE(instance,month,ordinal),
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    UNIQUE(id,instance,month),
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month)
) STRICT;

CREATE TABLE siren_device_counts (
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('cl1','meow')),
    hazard_level INTEGER NOT NULL,
    device_count INTEGER,
    compat_value_set_id INTEGER,
    PRIMARY KEY(instance,month,source,hazard_level),
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month)
) STRICT;

CREATE TABLE siren_device_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    ts TEXT,
    source TEXT CHECK(source IN ('cl1','meow')),
    hazard_level INTEGER,
    entry_kind TEXT NOT NULL DEFAULT 'record' CHECK(entry_kind IN ('record','value')),
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    UNIQUE(instance,month,ordinal),
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    UNIQUE(id,instance,month),
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month)
) STRICT;

CREATE TABLE action_point_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    ts TEXT,
    ap INTEGER,
    ap_total INTEGER,
    yellow_coin INTEGER,
    asset REAL,
    source TEXT,
    distance INTEGER,
    entry_kind TEXT NOT NULL DEFAULT 'record' CHECK(entry_kind IN ('record','value')),
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    UNIQUE(instance,month,ordinal),
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    UNIQUE(id,instance,month),
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month),
    CHECK(asset IS NULL OR asset BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE TABLE yellow_coin_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    ts TEXT,
    yellow_coin INTEGER,
    source TEXT,
    entry_kind TEXT NOT NULL DEFAULT 'record' CHECK(entry_kind IN ('record','value')),
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    UNIQUE(instance,month,ordinal),
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    UNIQUE(id,instance,month),
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month)
) STRICT;

CREATE TABLE coin_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    ts TEXT,
    yellow_coin INTEGER,
    purple_coin INTEGER,
    source TEXT,
    entry_kind TEXT NOT NULL DEFAULT 'record' CHECK(entry_kind IN ('record','value')),
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    UNIQUE(instance,month,ordinal),
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    UNIQUE(id,instance,month),
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month)
) STRICT;

CREATE TABLE commission_income (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    ts TEXT,
    commission_count INTEGER,
    entry_kind TEXT NOT NULL DEFAULT 'record' CHECK(entry_kind IN ('record','value')),
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    UNIQUE(instance,month,ordinal),
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    UNIQUE(id,instance,month),
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month)
) STRICT;

CREATE TABLE commission_income_items (
    income_id INTEGER NOT NULL REFERENCES commission_income(id) ON DELETE CASCADE,
    item TEXT NOT NULL,
    amount INTEGER,
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    compat_value_set_id INTEGER,
    PRIMARY KEY(income_id,item),
    FOREIGN KEY(income_id,instance,month) REFERENCES commission_income(id,instance,month) ON DELETE CASCADE,
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month)
) STRICT;

CREATE TABLE commission_income_screenshots (
    income_id INTEGER NOT NULL REFERENCES commission_income(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    path TEXT,
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    compat_value_set_id INTEGER,
    PRIMARY KEY(income_id,ordinal),
    FOREIGN KEY(income_id,instance,month) REFERENCES commission_income(id,instance,month) ON DELETE CASCADE,
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month)
) STRICT;

CREATE TABLE research_drops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    ts TEXT,
    completed_at TEXT,
    imgid TEXT,
    project TEXT,
    series INTEGER,
    entry_kind TEXT NOT NULL DEFAULT 'record' CHECK(entry_kind IN ('record','value')),
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    UNIQUE(instance,month,ordinal),
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    UNIQUE(id,instance,month),
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month)
) STRICT;

CREATE TABLE research_drop_items (
    drop_id INTEGER NOT NULL REFERENCES research_drops(id) ON DELETE CASCADE,
    item TEXT NOT NULL,
    amount INTEGER,
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    compat_value_set_id INTEGER,
    PRIMARY KEY(drop_id,item),
    FOREIGN KEY(drop_id,instance,month) REFERENCES research_drops(id,instance,month) ON DELETE CASCADE,
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month)
) STRICT;

CREATE TABLE gem_commission_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    ts TEXT,
    duration_hours INTEGER,
    gem_reward INTEGER,
    success INTEGER CHECK(success IN (0,1)),
    entry_kind TEXT NOT NULL DEFAULT 'record' CHECK(entry_kind IN ('record','value')),
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    UNIQUE(instance,month,ordinal),
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    UNIQUE(id,instance,month),
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month)
) STRICT;

CREATE TABLE running_gem_commissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    name TEXT,
    duration_hours INTEGER,
    created_at TEXT,
    finishes_at TEXT,
    entry_kind TEXT NOT NULL DEFAULT 'record' CHECK(entry_kind IN ('record','value')),
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    UNIQUE(instance,month,ordinal),
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    UNIQUE(id,instance,month),
    FOREIGN KEY(compat_value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month)
) STRICT;

CREATE TABLE ship_exp_checks (
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    checked_at TEXT,
    target_level INTEGER,
    fleet_index INTEGER,
    battle_count_at_check INTEGER,
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    PRIMARY KEY(instance)
) STRICT;

CREATE TABLE ship_exp_ships (
    instance TEXT NOT NULL REFERENCES ship_exp_checks(instance) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    position INTEGER,
    level INTEGER,
    current_exp INTEGER,
    total_exp INTEGER,
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    entry_kind TEXT NOT NULL DEFAULT 'record' CHECK(entry_kind IN ('record','value')),
    PRIMARY KEY(instance,ordinal),
    FOREIGN KEY(compat_value_set_id,instance) REFERENCES typed_value_sets(id,ship_instance)
) STRICT;

CREATE TABLE ship_exp_duration_groups (
    instance TEXT NOT NULL REFERENCES ship_exp_checks(instance) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('cl1_battle','meow_battle','cl1_round')),
    average_seconds REAL,
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    PRIMARY KEY(instance,kind),
    FOREIGN KEY(compat_value_set_id,instance) REFERENCES typed_value_sets(id,ship_instance),
    CHECK(average_seconds IS NULL OR average_seconds BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE TABLE ship_exp_duration_samples (
    instance TEXT NOT NULL,
    kind TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    duration_seconds REAL,
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    entry_kind TEXT NOT NULL DEFAULT 'number' CHECK(entry_kind IN ('number','value')),
    PRIMARY KEY(instance,kind,ordinal),
    FOREIGN KEY(instance,kind) REFERENCES ship_exp_duration_groups(instance,kind) ON DELETE CASCADE,
    FOREIGN KEY(compat_value_set_id,instance) REFERENCES typed_value_sets(id,ship_instance),
    CHECK(duration_seconds IS NULL OR duration_seconds BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE TABLE ship_exp_daily (
    instance TEXT NOT NULL REFERENCES ship_exp_checks(instance) ON DELETE CASCADE,
    day TEXT NOT NULL,
    total_run_time REAL,
    total_exp_gained INTEGER,
    battle_count INTEGER,
    field_mask INTEGER NOT NULL DEFAULT 0 CHECK(field_mask>=0),
    compat_value_set_id INTEGER,
    exp_per_hour REAL,
    PRIMARY KEY(instance,day),
    FOREIGN KEY(compat_value_set_id,instance) REFERENCES typed_value_sets(id,ship_instance),
    CHECK(total_run_time IS NULL OR total_run_time BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308),
    CHECK(exp_per_hour IS NULL OR exp_per_hour BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE TABLE daily_summary_task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    task TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT,
    duration_seconds REAL,
    CHECK(duration_seconds IS NULL OR duration_seconds BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE TABLE daily_summary_cl1_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    ts TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    estimated_exp INTEGER NOT NULL,
    CHECK(duration_seconds IS NULL OR duration_seconds BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE TABLE daily_summary_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    period_key TEXT NOT NULL,
    server TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    status TEXT NOT NULL,
    report_text TEXT,
    llm_attempts INTEGER NOT NULL DEFAULT 0,
    send_attempts INTEGER NOT NULL DEFAULT 0,
    error_kind TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(instance,period_key)
) STRICT;

CREATE TABLE daily_summary_collection_state (
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    task_tracking_started_at TEXT,
    cl1_tracking_started_at TEXT,
    PRIMARY KEY(instance)
) STRICT;

CREATE TABLE daily_summary_collection_gaps (
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    collection TEXT NOT NULL CHECK(collection IN ('task','cl1')),
    occurred_at TEXT NOT NULL,
    PRIMARY KEY(instance,collection,occurred_at)
) STRICT;

CREATE TABLE farming_aggregates (
    scope_key TEXT NOT NULL,
    hazard_level INTEGER NOT NULL CHECK(hazard_level BETWEEN 1 AND 6),
    instance TEXT REFERENCES storage_instances(instance),
    device_id TEXT,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('computed','legacy')),
    source_file TEXT,
    recorded_at INTEGER NOT NULL,
    effective_rounds REAL NOT NULL,
    average_yellow_coin REAL NOT NULL,
    average_plate REAL NOT NULL,
    average_abyssal REAL NOT NULL,
    average_obscure REAL NOT NULL,
    PRIMARY KEY(scope_key,hazard_level),
    CHECK((source_kind='legacy' AND source_file IS NOT NULL) OR (source_kind='computed' AND source_file IS NULL)),
    CHECK(effective_rounds IS NULL OR effective_rounds BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308),
    CHECK(average_yellow_coin IS NULL OR average_yellow_coin BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308),
    CHECK(average_plate IS NULL OR average_plate BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308),
    CHECK(average_abyssal IS NULL OR average_abyssal BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308),
    CHECK(average_obscure IS NULL OR average_obscure BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE TABLE scheduler_programs (
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    mode TEXT NOT NULL CHECK(mode IN ('native','enhance','takeover')),
    generation INTEGER NOT NULL DEFAULT 0,
    revision TEXT NOT NULL,
    PRIMARY KEY(instance)
) STRICT;

CREATE TABLE scheduler_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL REFERENCES scheduler_programs(instance) ON DELETE CASCADE,
    slot TEXT NOT NULL CHECK(slot IN ('draft','active')),
    schema_version INTEGER NOT NULL CHECK(schema_version=1),
    name TEXT NOT NULL,
    UNIQUE(instance,slot),
    UNIQUE(id,instance)
) STRICT;

CREATE TABLE scheduler_graphs (
    document_id INTEGER NOT NULL REFERENCES scheduler_documents(id) ON DELETE CASCADE,
    graph_no INTEGER NOT NULL CHECK(graph_no>=0),
    subgraph_id TEXT,
    name TEXT,
    pure INTEGER CHECK(pure IN (0,1)),
    entry_node TEXT NOT NULL,
    PRIMARY KEY(document_id,graph_no),
    CHECK((graph_no=0 AND subgraph_id IS NULL AND name IS NULL AND pure IS NULL) OR (graph_no>0 AND subgraph_id IS NOT NULL AND name IS NOT NULL AND pure IS NOT NULL))
) STRICT;

CREATE TABLE scheduler_nodes (
    document_id INTEGER NOT NULL,
    graph_no INTEGER NOT NULL,
    node_no INTEGER NOT NULL CHECK(node_no>=0),
    node_id TEXT NOT NULL,
    type TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(document_id,graph_no,node_no),
    FOREIGN KEY(document_id,graph_no) REFERENCES scheduler_graphs(document_id,graph_no) ON DELETE CASCADE
) STRICT;

CREATE TABLE scheduler_edges (
    document_id INTEGER NOT NULL,
    graph_no INTEGER NOT NULL,
    edge_no INTEGER NOT NULL CHECK(edge_no>=0),
    edge_id TEXT NOT NULL,
    source_node TEXT NOT NULL,
    source_port TEXT NOT NULL,
    target_node TEXT NOT NULL,
    target_port TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('control','data')),
    PRIMARY KEY(document_id,graph_no,edge_no),
    FOREIGN KEY(document_id,graph_no) REFERENCES scheduler_graphs(document_id,graph_no) ON DELETE CASCADE
) STRICT;

CREATE TABLE scheduler_graph_ports (
    document_id INTEGER NOT NULL,
    graph_no INTEGER NOT NULL CHECK(graph_no>0),
    direction TEXT NOT NULL CHECK(direction IN ('input','output')),
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('any','number','boolean','string','time','duration','resource','task','tasks','result','list','object')),
    required INTEGER NOT NULL CHECK(required IN (0,1)),
    PRIMARY KEY(document_id,graph_no,direction,ordinal),
    FOREIGN KEY(document_id,graph_no) REFERENCES scheduler_graphs(document_id,graph_no) ON DELETE CASCADE
) STRICT;

CREATE TABLE scheduler_viewport_fields (
    document_id INTEGER NOT NULL REFERENCES scheduler_documents(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('int','bigint','real')),
    int_value INTEGER,
    real_value REAL,
    text_value TEXT,
    PRIMARY KEY(document_id,name),
    CHECK((kind='int' AND int_value IS NOT NULL AND real_value IS NULL AND text_value IS NULL) OR (kind='real' AND int_value IS NULL AND real_value IS NOT NULL AND real_value BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308 AND text_value IS NULL) OR (kind='bigint' AND int_value IS NULL AND real_value IS NULL AND text_value IS NOT NULL)),
    CHECK(real_value IS NULL OR real_value BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE TABLE scheduler_node_positions (
    document_id INTEGER NOT NULL,
    graph_no INTEGER NOT NULL,
    node_no INTEGER NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('int','bigint','real')),
    int_value INTEGER,
    real_value REAL,
    text_value TEXT,
    PRIMARY KEY(document_id,graph_no,node_no,name),
    FOREIGN KEY(document_id,graph_no,node_no) REFERENCES scheduler_nodes(document_id,graph_no,node_no) ON DELETE CASCADE,
    CHECK((kind='int' AND int_value IS NOT NULL AND real_value IS NULL AND text_value IS NULL) OR (kind='real' AND int_value IS NULL AND real_value IS NOT NULL AND real_value BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308 AND text_value IS NULL) OR (kind='bigint' AND int_value IS NULL AND real_value IS NULL AND text_value IS NOT NULL)),
    CHECK(real_value IS NULL OR real_value BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE TABLE typed_value_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    document_id INTEGER,
    month TEXT,
    runtime_instance TEXT REFERENCES storage_instances(instance),
    ship_instance TEXT REFERENCES ship_exp_checks(instance) ON DELETE CASCADE,
    UNIQUE(id,instance),
    UNIQUE(id,document_id),
    UNIQUE(id,instance,month),
    UNIQUE(id,runtime_instance),
    UNIQUE(id,ship_instance),
    FOREIGN KEY(document_id,instance) REFERENCES scheduler_documents(id,instance) ON DELETE CASCADE,
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    CHECK((document_id IS NOT NULL)+(month IS NOT NULL)+(runtime_instance IS NOT NULL)+(ship_instance IS NOT NULL)=1),
    CHECK(runtime_instance IS NULL OR runtime_instance=instance),
    CHECK(ship_instance IS NULL OR ship_instance=instance)
) STRICT;

CREATE TABLE typed_value_nodes (
    value_set_id INTEGER NOT NULL REFERENCES typed_value_sets(id) ON DELETE CASCADE,
    node_no INTEGER NOT NULL,
    parent_no INTEGER,
    member_key TEXT,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    kind TEXT NOT NULL,
    int_value INTEGER,
    real_value REAL,
    text_value TEXT,
    PRIMARY KEY(value_set_id,node_no),
    FOREIGN KEY(value_set_id,parent_no) REFERENCES typed_value_nodes(value_set_id,node_no) ON DELETE CASCADE,
    CHECK((parent_no IS NULL AND node_no=1 AND member_key IS NULL AND ordinal=0) OR (parent_no IS NOT NULL AND parent_no<node_no)),
    CHECK(CASE kind WHEN 'null' THEN int_value IS NULL AND real_value IS NULL AND text_value IS NULL WHEN 'object' THEN int_value IS NULL AND real_value IS NULL AND text_value IS NULL WHEN 'array' THEN int_value IS NULL AND real_value IS NULL AND text_value IS NULL WHEN 'bool' THEN int_value IN (0,1) AND int_value IS NOT NULL AND real_value IS NULL AND text_value IS NULL WHEN 'int' THEN int_value IS NOT NULL AND real_value IS NULL AND text_value IS NULL WHEN 'bigint' THEN int_value IS NULL AND real_value IS NULL AND text_value IS NOT NULL WHEN 'real' THEN int_value IS NULL AND real_value IS NOT NULL AND real_value BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308 AND text_value IS NULL WHEN 'special_real' THEN int_value IS NULL AND real_value IS NULL AND text_value IN ('nan','+inf','-inf') AND text_value IS NOT NULL WHEN 'string' THEN int_value IS NULL AND real_value IS NULL AND text_value IS NOT NULL ELSE 0 END),
    CHECK(real_value IS NULL OR real_value BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE UNIQUE INDEX value_one_root ON typed_value_nodes(value_set_id) WHERE parent_no IS NULL;

CREATE UNIQUE INDEX value_child_order ON typed_value_nodes(value_set_id,parent_no,ordinal) WHERE parent_no IS NOT NULL;

CREATE UNIQUE INDEX value_object_key ON typed_value_nodes(value_set_id,parent_no,member_key) WHERE member_key IS NOT NULL;

CREATE TRIGGER value_parent_shape BEFORE INSERT ON typed_value_nodes WHEN NEW.parent_no IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS (
 SELECT 1 FROM typed_value_nodes p WHERE p.value_set_id=NEW.value_set_id AND p.node_no=NEW.parent_no AND
 ((p.kind='object' AND NEW.member_key IS NOT NULL) OR (p.kind='array' AND NEW.member_key IS NULL)))
 THEN RAISE(ABORT,'invalid parent') END;
END;

CREATE TRIGGER value_special_real_scope BEFORE INSERT ON typed_value_nodes WHEN NEW.kind='special_real' BEGIN
 SELECT CASE WHEN NOT EXISTS (
 SELECT 1 FROM typed_value_sets WHERE id=NEW.value_set_id AND (month IS NOT NULL OR ship_instance IS NOT NULL))
 THEN RAISE(ABORT,'scheduler disallows special float') END;
END;

CREATE TRIGGER value_immutable BEFORE UPDATE ON typed_value_nodes BEGIN SELECT RAISE(ABORT,'immutable value'); END;

CREATE TABLE scheduler_variable_definitions (
    document_id INTEGER NOT NULL REFERENCES scheduler_documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('any','number','boolean','string','time','duration','resource','task','tasks','result','list','object')),
    value_set_id INTEGER NOT NULL,
    persistent INTEGER NOT NULL CHECK(persistent IN (0,1)),
    PRIMARY KEY(document_id,ordinal),
    FOREIGN KEY(value_set_id,document_id) REFERENCES typed_value_sets(id,document_id) ON DELETE CASCADE
) STRICT;

CREATE TABLE scheduler_node_parameters (
    document_id INTEGER NOT NULL,
    graph_no INTEGER NOT NULL,
    node_no INTEGER NOT NULL,
    name TEXT NOT NULL,
    value_set_id INTEGER NOT NULL,
    PRIMARY KEY(document_id,graph_no,node_no,name),
    FOREIGN KEY(document_id,graph_no,node_no) REFERENCES scheduler_nodes(document_id,graph_no,node_no) ON DELETE CASCADE,
    FOREIGN KEY(value_set_id,document_id) REFERENCES typed_value_sets(id,document_id) ON DELETE CASCADE
) STRICT;

CREATE TABLE scheduler_state_variables (
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    name TEXT NOT NULL,
    value_set_id INTEGER NOT NULL,
    PRIMARY KEY(instance,name),
    FOREIGN KEY(value_set_id,instance) REFERENCES typed_value_sets(id,runtime_instance) ON DELETE CASCADE
) STRICT;

CREATE TABLE scheduler_runtime (
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    in_flight TEXT,
    record_mask INTEGER NOT NULL DEFAULT 0 CHECK(record_mask BETWEEN 0 AND 63),
    PRIMARY KEY(instance)
) STRICT;

CREATE TABLE scheduler_counters (
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    kind TEXT NOT NULL CHECK(kind IN ('rotation','quota')),
    record_key TEXT NOT NULL,
    server_day TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY(instance,kind,record_key,server_day),
    CHECK((kind='rotation' AND server_day='') OR (kind='quota' AND length(server_day)=10))
) STRICT;

CREATE TABLE scheduler_times (
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    kind TEXT NOT NULL CHECK(kind IN ('last_executed','cooldown')),
    record_key TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(instance,kind,record_key)
) STRICT;

CREATE TABLE scheduler_results (
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    scope TEXT NOT NULL CHECK(scope IN ('task','last')),
    record_key TEXT NOT NULL,
    task TEXT,
    status TEXT,
    reason TEXT,
    finished_at TEXT,
    field_mask INTEGER NOT NULL CHECK(field_mask BETWEEN 0 AND 15),
    compat_value_set_id INTEGER,
    PRIMARY KEY(instance,scope,record_key),
    CHECK(scope='task' OR record_key=''),
    FOREIGN KEY(compat_value_set_id,instance) REFERENCES typed_value_sets(id,runtime_instance)
) STRICT;

CREATE TABLE scheduler_observations (
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    resource TEXT NOT NULL,
    value REAL,
    resource_limit REAL,
    total REAL,
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY(instance,resource),
    CHECK(value IS NULL OR value BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308),
    CHECK(resource_limit IS NULL OR resource_limit BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308),
    CHECK(total IS NULL OR total BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308)
) STRICT;

CREATE TABLE scheduler_record_extensions (
    instance TEXT NOT NULL REFERENCES storage_instances(instance),
    name TEXT NOT NULL,
    value_set_id INTEGER NOT NULL,
    PRIMARY KEY(instance,name),
    FOREIGN KEY(value_set_id,instance) REFERENCES typed_value_sets(id,runtime_instance) ON DELETE CASCADE
) STRICT;

CREATE TRIGGER value_set_owner_immutable BEFORE UPDATE OF instance,document_id,month,runtime_instance,ship_instance ON typed_value_sets BEGIN SELECT RAISE(ABORT,'immutable owner'); END;

CREATE TRIGGER scheduler_state_variables_runtime_scope_insert BEFORE INSERT ON scheduler_state_variables BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM typed_value_sets WHERE id=NEW.value_set_id AND instance=NEW.instance AND runtime_instance=NEW.instance)
 THEN RAISE(ABORT,'document value used as runtime') END; END;

CREATE TRIGGER scheduler_state_variables_runtime_scope_update BEFORE UPDATE ON scheduler_state_variables BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM typed_value_sets WHERE id=NEW.value_set_id AND instance=NEW.instance AND runtime_instance=NEW.instance)
 THEN RAISE(ABORT,'document value used as runtime') END; END;

CREATE TRIGGER scheduler_record_extensions_runtime_scope_insert BEFORE INSERT ON scheduler_record_extensions BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM typed_value_sets WHERE id=NEW.value_set_id AND instance=NEW.instance AND runtime_instance=NEW.instance)
 THEN RAISE(ABORT,'document value used as runtime') END; END;

CREATE TRIGGER scheduler_record_extensions_runtime_scope_update BEFORE UPDATE ON scheduler_record_extensions BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM typed_value_sets WHERE id=NEW.value_set_id AND instance=NEW.instance AND runtime_instance=NEW.instance)
 THEN RAISE(ABORT,'document value used as runtime') END; END;

CREATE TABLE cl1_compat_fields (
    instance TEXT NOT NULL,
    month TEXT NOT NULL,
    name TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('value','extra')),
    value_set_id INTEGER NOT NULL,
    PRIMARY KEY(instance,month,name),
    FOREIGN KEY(instance,month) REFERENCES cl1_months(instance,month) ON DELETE CASCADE,
    FOREIGN KEY(value_set_id,instance,month) REFERENCES typed_value_sets(id,instance,month)
) STRICT;

CREATE TABLE ship_exp_compat_fields (
    instance TEXT NOT NULL REFERENCES ship_exp_checks(instance) ON DELETE CASCADE,
    name TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('value','extra')),
    value_set_id INTEGER NOT NULL,
    PRIMARY KEY(instance,name),
    FOREIGN KEY(value_set_id,instance) REFERENCES typed_value_sets(id,ship_instance)
) STRICT;

CREATE INDEX resource_snapshots_window ON resource_snapshots(instance,ts,id);

CREATE INDEX resource_flows_window ON resource_flows(instance,ts,id);

CREATE INDEX opsi_items_scope_window ON opsi_items(instance,device_id,genre,created_at,id);

CREATE INDEX opsi_items_global_window ON opsi_items(device_id,genre,created_at,id);

CREATE INDEX opsi_items_scope_image ON opsi_items(instance,device_id,imgid,id);

CREATE INDEX opsi_items_image ON opsi_items(imgid);

CREATE INDEX research_drops_image ON research_drops(instance,imgid,month,ordinal);

CREATE INDEX running_commissions_finish ON running_gem_commissions(instance,month,finishes_at,id);

CREATE INDEX running_commissions_match ON running_gem_commissions(instance,name,created_at,duration_hours);

CREATE INDEX storage_scans_window ON storage_scans(instance,finished_at,id);

CREATE INDEX daily_summary_tasks_window ON daily_summary_task_runs(instance,finished_at,id);

CREATE INDEX daily_summary_cl1_window ON daily_summary_cl1_events(instance,ts,id);

CREATE INDEX daily_summary_period_cleanup ON daily_summary_periods(window_end);

CREATE INDEX akashi_ap_purchases_window ON akashi_ap_purchases(instance,ts,id);

CREATE INDEX siren_device_events_window ON siren_device_events(instance,ts,id);

CREATE INDEX action_point_snapshots_window ON action_point_snapshots(instance,ts,id);

CREATE INDEX yellow_coin_snapshots_window ON yellow_coin_snapshots(instance,ts,id);

CREATE INDEX coin_snapshots_window ON coin_snapshots(instance,ts,id);

CREATE INDEX commission_income_window ON commission_income(instance,ts,id);

CREATE INDEX research_drops_window ON research_drops(instance,ts,id);

CREATE INDEX gem_commission_history_window ON gem_commission_history(instance,ts,id);
