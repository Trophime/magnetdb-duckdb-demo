# Streaming Operational Data Architecture

## Overview

This document describes the architectural extension to support **real-time streaming operational data** in addition to the existing batch-oriented workflow.

### Current vs. Streaming

```
Current (Batch):
Experiment runs → Files written → Post-processing → Analysis
                  (Hours/days later)

Streaming (Real-time):
Sensors → Continuous data → Immediate processing → Live dashboards
         (Milliseconds/seconds)
```

## Extended Architecture

### High-Level View

```
┌─────────────────────────────────────────────────────────────────┐
│                    STREAMING LAYER (NEW)                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐      ┌──────────────┐     ┌──────────────┐  │
│  │   Apache     │      │ TimescaleDB  │     │   InfluxDB   │  │
│  │   Kafka      │─────►│  (Time-series│     │  (Metrics)   │  │
│  │ (Event Bus)  │      │    SQL)      │     │  (optional)  │  │
│  └──────┬───────┘      └──────┬───────┘     └──────┬───────┘  │
│         │                     │                     │           │
│  Real-time ingest      SQL queries            High-freq        │
│  Event streaming       Aggregations           metrics          │
│                                                                  │
└─────────┼─────────────────────┼─────────────────────┼───────────┘
          │                     │                     │
          │ Archival            │ Analytics           │ Monitoring
          │                     │                     │
┌─────────▼─────────────────────▼─────────────────────▼───────────┐
│              EXISTING BATCH LAYER                                │
│  PostgreSQL (metadata) + SeaweedFS (archives) + Celery           │
└──────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
Real-time Operation:
┌───────────────┐
│  Magnet       │
│  Sensors      │  ← Current, voltage, temperature,
│               │    field, strain, position, etc.
└───────┬───────┘
        │ Continuous stream
        │ (ms to seconds)
        ↓
┌───────────────┐
│  Data         │
│  Acquisition  │  ← LabVIEW, custom DAQ
│  System       │
└───────┬───────┘
        │ MQTT, Kafka producer, HTTP
        ↓
┌───────────────┐
│  Kafka        │  ← Message buffer
│  Topics       │    - device.{id}.magnetometer
│               │    - device.{id}.temperature
└───────┬───────┘    - device.{id}.power
        │
        ├──────────────────┬──────────────────┐
        │                  │                  │
        ↓                  ↓                  ↓
┌───────────────┐  ┌───────────────┐  ┌──────────────┐
│ TimescaleDB   │  │ Stream        │  │ Dashboards   │
│ (Store)       │  │ Processor     │  │ (Monitor)    │
│               │  │ (Analyze)     │  │              │
└───────┬───────┘  └───────────────┘  └──────────────┘
        │
        │ After run completes
        ↓
┌───────────────┐
│ Archival      │
│ to SeaweedFS  │  ← Compress, store long-term
│ (HDF5/Parquet)│
└───────────────┘
```

## Technology Stack

### Components

| Component | Technology | Purpose | Why |
|-----------|-----------|---------|-----|
| **Message Queue** | Apache Kafka | Event streaming, buffer | Industry standard, proven at scale |
| **Time-Series DB** | TimescaleDB | Hot data storage, SQL queries | PostgreSQL extension, familiar syntax |
| **Metrics DB** | InfluxDB (optional) | High-frequency metrics | Optimized for time-series, good for dashboards |
| **Stream Processing** | Python + Kafka Consumer | Real-time analytics | Integrate with existing Python stack |
| **Visualization** | Grafana | Live dashboards | Time-series visualization |

### Why These Choices?

**Kafka over RabbitMQ/Redis:**
- Better for high-throughput streaming
- Replay capability (important for debugging)
- Durable message storage
- De facto standard for data pipelines

**TimescaleDB over InfluxDB alone:**
- SQL interface (familiar to team)
- PostgreSQL ecosystem (same as main DB)
- Better for complex queries
- Can still use InfluxDB for pure metrics

**Python Stream Processing over Flink/Spark:**
- Simpler operational model
- Integrate with existing Celery workers
- Good enough for medium-scale (< 100k msgs/sec)
- Can upgrade to Flink later if needed

## Docker Compose Configuration

```yaml
version: '3.8'

services:
  # === EXISTING SERVICES ===
  postgres:
    # ... existing config ...

  seaweedfs-master:
    # ... existing config ...

  # === NEW STREAMING SERVICES ===

  # Zookeeper (required by Kafka)
  zookeeper:
    image: confluentinc/cp-zookeeper:7.5.0
    container_name: zookeeper
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    volumes:
      - zookeeper_data:/var/lib/zookeeper/data
      - zookeeper_log:/var/lib/zookeeper/log
    networks:
      - magnetdb-network
    restart: unless-stopped

  # Kafka message broker
  kafka:
    image: confluentinc/cp-kafka:7.5.0
    container_name: kafka
    depends_on:
      - zookeeper
    ports:
      - "9092:9092"
      - "9094:9094"
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_LISTENERS: INTERNAL://0.0.0.0:9092,OUTSIDE://0.0.0.0:9094
      KAFKA_ADVERTISED_LISTENERS: INTERNAL://kafka:9092,OUTSIDE://localhost:9094
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: INTERNAL:PLAINTEXT,OUTSIDE:PLAINTEXT
      KAFKA_INTER_BROKER_LISTENER_NAME: INTERNAL
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_LOG_RETENTION_HOURS: 168  # 7 days
      KAFKA_LOG_SEGMENT_BYTES: 1073741824  # 1GB
    volumes:
      - kafka_data:/var/lib/kafka/data
    networks:
      - magnetdb-network
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "kafka-broker-api-versions", "--bootstrap-server", "localhost:9092"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Kafka UI (for monitoring)
  kafka-ui:
    image: provectuslabs/kafka-ui:latest
    container_name: kafka-ui
    depends_on:
      - kafka
    ports:
      - "8090:8080"
    environment:
      KAFKA_CLUSTERS_0_NAME: magnetdb
      KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS: kafka:9092
    networks:
      - magnetdb-network

  # TimescaleDB for time-series data
  timescaledb:
    image: timescale/timescaledb:latest-pg14
    container_name: timescaledb
    ports:
      - "5433:5432"
    environment:
      POSTGRES_DB: magnetdb_timeseries
      POSTGRES_USER: magnetdb
      POSTGRES_PASSWORD: ${TIMESCALE_PASSWORD}
    volumes:
      - timescale_data:/var/lib/postgresql/data
      - ./timescaledb/init.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - magnetdb-network
    restart: unless-stopped

  # InfluxDB (optional - for pure metrics)
  influxdb:
    image: influxdb:2.7
    container_name: influxdb
    ports:
      - "8086:8086"
    environment:
      DOCKER_INFLUXDB_INIT_MODE: setup
      DOCKER_INFLUXDB_INIT_USERNAME: admin
      DOCKER_INFLUXDB_INIT_PASSWORD: ${INFLUX_PASSWORD}
      DOCKER_INFLUXDB_INIT_ORG: lncmi
      DOCKER_INFLUXDB_INIT_BUCKET: operational_data
      DOCKER_INFLUXDB_INIT_RETENTION: 30d
    volumes:
      - influxdb_data:/var/lib/influxdb2
    networks:
      - magnetdb-network
    restart: unless-stopped

  # Stream processor
  stream-processor:
    build: ./stream_processor
    container_name: stream-processor
    depends_on:
      kafka:
        condition: service_healthy
      timescaledb:
        condition: service_started
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      TIMESCALE_URL: postgresql://magnetdb:${TIMESCALE_PASSWORD}@timescaledb:5432/magnetdb_timeseries
      POSTGRES_URL: postgresql://magnetdb:${POSTGRES_PASSWORD}@postgres:5432/magnetdb
    networks:
      - magnetdb-network
    restart: unless-stopped

  # Grafana for visualization
  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD}
      GF_INSTALL_PLUGINS: grafana-clock-panel
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning
    depends_on:
      - timescaledb
      - influxdb
    networks:
      - magnetdb-network
    restart: unless-stopped

volumes:
  zookeeper_data:
  zookeeper_log:
  kafka_data:
  timescale_data:
  influxdb_data:
  grafana_data:

networks:
  magnetdb-network:
    driver: bridge
```

## TimescaleDB Schema

```sql
-- timescaledb/init.sql

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Sensor readings table (hypertable)
CREATE TABLE sensor_readings (
    time TIMESTAMPTZ NOT NULL,
    device_id TEXT NOT NULL,
    sensor_type TEXT NOT NULL,  -- magnetometer, temperature, voltage, current, strain, position
    channel INT,                 -- For multi-channel sensors
    value DOUBLE PRECISION,
    unit TEXT,                   -- A, V, T, K, MPa, mm
    quality SMALLINT,            -- 0=good, 1=warning, 2=bad
    metadata JSONB
);

-- Convert to hypertable (partitioned by time)
SELECT create_hypertable('sensor_readings', 'time');

-- Indexes for efficient queries
CREATE INDEX idx_device_sensor_time ON sensor_readings (device_id, sensor_type, time DESC);
CREATE INDEX idx_sensor_type_time ON sensor_readings (sensor_type, time DESC);
CREATE INDEX idx_metadata ON sensor_readings USING GIN (metadata);

-- Retention policy (auto-delete old data after 1 year)
SELECT add_retention_policy('sensor_readings', INTERVAL '1 year');

-- Compression policy (compress data older than 7 days)
ALTER TABLE sensor_readings SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'device_id, sensor_type'
);
SELECT add_compression_policy('sensor_readings', INTERVAL '7 days');

-- Continuous aggregates for fast queries (1 minute resolution)
CREATE MATERIALIZED VIEW sensor_readings_1min
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 minute', time) AS bucket,
    device_id,
    sensor_type,
    channel,
    AVG(value) as avg_value,
    MAX(value) as max_value,
    MIN(value) as min_value,
    STDDEV(value) as stddev_value,
    COUNT(*) as sample_count
FROM sensor_readings
GROUP BY bucket, device_id, sensor_type, channel;

-- Refresh policy for continuous aggregate
SELECT add_continuous_aggregate_policy('sensor_readings_1min',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute');

-- 1 hour resolution aggregate
CREATE MATERIALIZED VIEW sensor_readings_1hour
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 hour', time) AS bucket,
    device_id,
    sensor_type,
    AVG(value) as avg_value,
    MAX(value) as max_value,
    MIN(value) as min_value
FROM sensor_readings
GROUP BY bucket, device_id, sensor_type;

-- Events table (for anomalies, alerts, state changes)
CREATE TABLE device_events (
    time TIMESTAMPTZ NOT NULL,
    device_id TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- alarm, warning, state_change, calibration
    severity TEXT,             -- info, warning, error, critical
    message TEXT,
    metadata JSONB
);

SELECT create_hypertable('device_events', 'time');
CREATE INDEX idx_device_event_time ON device_events (device_id, event_type, time DESC);

-- Experimental run metadata (links to main PostgreSQL)
CREATE TABLE streaming_runs (
    run_id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    status TEXT,  -- streaming, paused, completed, aborted
    target_current DOUBLE PRECISION,
    target_field DOUBLE PRECISION,
    metadata JSONB
);
```

## Python Stream Processing

### Streaming Service

```python
# stream_processor/streaming_service.py
import os
import json
import logging
from datetime import datetime
from typing import Dict, Any
from kafka import KafkaConsumer, KafkaProducer
import psycopg2
from psycopg2.extras import execute_batch

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StreamProcessor:
    """Process streaming operational data from Kafka"""
    
    def __init__(self):
        # Kafka consumer
        self.consumer = KafkaConsumer(
            bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092'),
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id='magnetdb-stream-processor',
            auto_offset_reset='latest',
            enable_auto_commit=True
        )
        
        # Subscribe to device topics
        self.consumer.subscribe(pattern='^device\..*')
        
        # Kafka producer (for processed events)
        self.producer = KafkaProducer(
            bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS'),
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        
        # TimescaleDB connection
        self.timescale_conn = psycopg2.connect(
            os.getenv('TIMESCALE_URL')
        )
        
        # PostgreSQL connection (main DB)
        self.postgres_conn = psycopg2.connect(
            os.getenv('POSTGRES_URL')
        )
        
        # Batch insert buffer
        self.buffer = []
        self.buffer_size = 1000
        
        logger.info("Stream processor initialized")
    
    def process_stream(self):
        """Main processing loop"""
        
        logger.info("Starting stream processing...")
        
        try:
            for message in self.consumer:
                try:
                    self._process_message(message)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self._flush_buffer()
            self.consumer.close()
            self.timescale_conn.close()
            self.postgres_conn.close()
    
    def _process_message(self, message):
        """Process single Kafka message"""
        
        topic = message.topic
        data = message.value
        
        # Parse topic: device.{device_id}.{sensor_type}
        parts = topic.split('.')
        if len(parts) != 3 or parts[0] != 'device':
            logger.warning(f"Invalid topic format: {topic}")
            return
        
        device_id = parts[1]
        sensor_type = parts[2]
        
        # Store in TimescaleDB
        self._store_reading(data)
        
        # Real-time analytics
        if self._is_anomaly(data):
            self._handle_anomaly(device_id, sensor_type, data)
        
        # Update live dashboard
        self._update_dashboard(device_id, sensor_type, data)
    
    def _store_reading(self, data: Dict[str, Any]):
        """Buffer reading for batch insert into TimescaleDB"""
        
        reading = (
            data['timestamp'],
            data['device_id'],
            data['sensor_type'],
            data.get('channel'),
            data['value'],
            data.get('unit'),
            data.get('quality', 0),
            json.dumps(data.get('metadata', {}))
        )
        
        self.buffer.append(reading)
        
        if len(self.buffer) >= self.buffer_size:
            self._flush_buffer()
    
    def _flush_buffer(self):
        """Batch insert buffered readings"""
        
        if not self.buffer:
            return
        
        with self.timescale_conn.cursor() as cur:
            execute_batch(cur, """
                INSERT INTO sensor_readings 
                (time, device_id, sensor_type, channel, value, unit, quality, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, self.buffer)
        
        self.timescale_conn.commit()
        logger.info(f"Inserted {len(self.buffer)} readings")
        self.buffer = []
    
    def _is_anomaly(self, data: Dict[str, Any]) -> bool:
        """Detect anomalies in real-time"""
        
        sensor_type = data['sensor_type']
        value = data['value']
        
        # Simple threshold-based detection
        # TODO: Implement ML-based anomaly detection
        thresholds = {
            'current': (0, 15000),  # Amps
            'voltage': (0, 1000),   # Volts
            'temperature': (0, 400), # K
            'field': (0, 50),       # Tesla
        }
        
        if sensor_type in thresholds:
            min_val, max_val = thresholds[sensor_type]
            if value < min_val or value > max_val:
                return True
        
        return False
    
    def _handle_anomaly(self, device_id: str, sensor_type: str, data: Dict):
        """Handle detected anomaly"""
        
        logger.warning(f"Anomaly detected: {device_id} {sensor_type} = {data['value']}")
        
        # Store event in TimescaleDB
        with self.timescale_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO device_events 
                (time, device_id, event_type, severity, message, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                data['timestamp'],
                device_id,
                'anomaly',
                'warning',
                f"{sensor_type} out of range: {data['value']}",
                json.dumps(data)
            ))
        self.timescale_conn.commit()
        
        # Send alert to Kafka (for notifications)
        self.producer.send('alerts', value={
            'device_id': device_id,
            'sensor_type': sensor_type,
            'timestamp': data['timestamp'],
            'value': data['value'],
            'severity': 'warning'
        })
    
    def _update_dashboard(self, device_id: str, sensor_type: str, data: Dict):
        """Send update to live dashboard (via WebSocket or Server-Sent Events)"""
        # TODO: Implement WebSocket/SSE for live updates
        pass

if __name__ == '__main__':
    processor = StreamProcessor()
    processor.process_stream()
```

### Data Ingestion Client

```python
# services/streaming_ingestion.py
import os
import json
from datetime import datetime
from kafka import KafkaProducer
from typing import Optional, Dict, Any

class StreamingDataIngestion:
    """Client for ingesting real-time operational data"""
    
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092'),
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            compression_type='gzip',
            batch_size=16384,
            linger_ms=10
        )
    
    def ingest_sensor_reading(self,
                             device_id: str,
                             sensor_type: str,
                             timestamp: datetime,
                             value: float,
                             channel: Optional[int] = None,
                             unit: Optional[str] = None,
                             quality: int = 0,
                             metadata: Optional[Dict] = None):
        """Ingest single sensor reading"""
        
        message = {
            'device_id': device_id,
            'sensor_type': sensor_type,
            'timestamp': timestamp.isoformat(),
            'value': value,
            'channel': channel,
            'unit': unit,
            'quality': quality,
            'metadata': metadata or {}
        }
        
        # Send to device-specific topic
        topic = f"device.{device_id}.{sensor_type}"
        self.producer.send(topic, value=message)
    
    def ingest_batch(self, readings: list):
        """Ingest multiple readings efficiently"""
        for reading in readings:
            self.ingest_sensor_reading(**reading)
        
        # Wait for all messages to be sent
        self.producer.flush()
    
    def start_run(self, run_id: str, device_id: str, metadata: Dict):
        """Mark start of experimental run"""
        
        self.producer.send('experimental-runs', value={
            'event': 'run_started',
            'run_id': run_id,
            'device_id': device_id,
            'timestamp': datetime.now().isoformat(),
            'metadata': metadata
        })
        
        self.producer.flush()
    
    def end_run(self, run_id: str):
        """Mark end of experimental run"""
        
        self.producer.send('experimental-runs', value={
            'event': 'run_ended',
            'run_id': run_id,
            'timestamp': datetime.now().isoformat()
        })
        
        self.producer.flush()

# Singleton
streaming = StreamingDataIngestion()
```

### Integration with DAQ Systems

```python
# Example: LabVIEW integration via HTTP
from fastapi import APIRouter
from services.streaming_ingestion import streaming

router = APIRouter(prefix="/api/streaming")

@router.post("/ingest")
async def ingest_sensor_data(
    device_id: str,
    sensor_type: str,
    readings: list
):
    """Endpoint for LabVIEW or other DAQ systems to push data"""
    
    for reading in readings:
        streaming.ingest_sensor_reading(
            device_id=device_id,
            sensor_type=sensor_type,
            timestamp=datetime.fromisoformat(reading['timestamp']),
            value=reading['value'],
            channel=reading.get('channel'),
            unit=reading.get('unit')
        )
    
    return {"status": "ok", "count": len(readings)}

@router.post("/runs/{run_id}/start")
async def start_streaming_run(run_id: str, device_id: str):
    """Start streaming experimental run"""
    
    # Register in main database
    run = ExperimentalRun(
        id=run_id,
        device_id=device_id,
        run_date=datetime.now(),
        status='streaming',
        stream_active=True
    )
    db.add(run)
    db.commit()
    
    # Notify stream processor
    streaming.start_run(run_id, device_id, {})
    
    return {"status": "started", "run_id": run_id}

@router.post("/runs/{run_id}/end")
async def end_streaming_run(run_id: str):
    """End streaming experimental run and trigger archival"""
    
    run = db.query(ExperimentalRun).get(run_id)
    run.stream_active = False
    run.status = 'archiving'
    db.commit()
    
    # Notify stream processor
    streaming.end_run(run_id)
    
    # Trigger archival job (async)
    from tasks import archive_streaming_run
    archive_streaming_run.delay(run_id)
    
    return {"status": "ended", "run_id": run_id}
```

## Archival: Stream → Batch

```python
# tasks.py
@celery_app.task
def archive_streaming_run(run_id: str):
    """Archive streaming data from TimescaleDB to SeaweedFS"""
    
    run = db.query(ExperimentalRun).get(run_id)
    
    logger.info(f"Archiving streaming run {run_id}")
    
    # Query all data from TimescaleDB
    timescale_conn = psycopg2.connect(os.getenv('TIMESCALE_URL'))
    
    query = """
        SELECT time, sensor_type, channel, value, unit, quality, metadata
        FROM sensor_readings
        WHERE device_id = %s
        AND time BETWEEN %s AND %s
        ORDER BY time, sensor_type
    """
    
    with timescale_conn.cursor() as cur:
        cur.execute(query, (run.device_id, run.started_at, run.ended_at))
        data = cur.fetchall()
    
    logger.info(f"Retrieved {len(data)} records")
    
    # Convert to HDF5 for efficient storage
    import h5py
    import tempfile
    import numpy as np
    
    with tempfile.NamedTemporaryFile(suffix='.h5', delete=False) as tmp:
        with h5py.File(tmp.name, 'w') as hf:
            # Group by sensor type
            sensor_types = set(row[1] for row in data)
            
            for sensor_type in sensor_types:
                sensor_data = [row for row in data if row[1] == sensor_type]
                
                grp = hf.create_group(sensor_type)
                grp.create_dataset('timestamps', 
                    data=np.array([row[0].timestamp() for row in sensor_data]))
                grp.create_dataset('values', 
                    data=np.array([row[3] for row in sensor_data]))
                if sensor_data[0][2] is not None:  # channel
                    grp.create_dataset('channels', 
                        data=np.array([row[2] for row in sensor_data]))
                
                # Metadata
                grp.attrs['unit'] = sensor_data[0][4] or ''
                grp.attrs['sample_count'] = len(sensor_data)
        
        # Upload to SeaweedFS
        from services.storage import storage
        archive_path = storage.upload_device_artifact(
            device_id=run.device_id,
            artifact_type='archived_stream',
            local_file=tmp.name,
            metadata={
                'run_id': run_id,
                'record_count': len(data),
                'sensor_types': list(sensor_types)
            }
        )
        
        os.unlink(tmp.name)
    
    # Register as computed dataset
    archived = ComputedDataset(
        id=f"archived_{run_id}",
        experimental_run_id=run_id,
        dataset_type='archived_timeseries',
        minio_path=archive_path,
        description=f'Archived streaming data from run {run_id}',
        version=1
    )
    db.add(archived)
    
    # Update run status
    run.status = 'completed'
    db.commit()
    
    logger.info(f"Archived to {archive_path}")
    
    # Optional: Delete from TimescaleDB to save space
    # with timescale_conn.cursor() as cur:
    #     cur.execute("DELETE FROM sensor_readings WHERE device_id = %s AND time BETWEEN %s AND %s",
    #                 (run.device_id, run.started_at, run.ended_at))
    # timescale_conn.commit()
```

## Querying Patterns

### Live Data (TimescaleDB)

```python
@router.get("/devices/{device_id}/live-data")
async def get_live_data(
    device_id: str,
    sensor_type: Optional[str] = None,
    minutes: int = 5
):
    """Get recent live data (last N minutes)"""
    
    query = """
        SELECT time, sensor_type, value, unit
        FROM sensor_readings
        WHERE device_id = %s
        AND time > NOW() - INTERVAL '%s minutes'
    """
    
    params = [device_id, minutes]
    
    if sensor_type:
        query += " AND sensor_type = %s"
        params.append(sensor_type)
    
    query += " ORDER BY time DESC LIMIT 1000"
    
    # Execute query
    # ... return results

@router.get("/devices/{device_id}/aggregated")
async def get_aggregated_data(
    device_id: str,
    sensor_type: str,
    resolution: str = '1min'  # 1min, 1hour, 1day
):
    """Get aggregated data using continuous aggregates"""
    
    view = f"sensor_readings_{resolution}"
    
    query = f"""
        SELECT bucket, avg_value, max_value, min_value
        FROM {view}
        WHERE device_id = %s AND sensor_type = %s
        AND bucket > NOW() - INTERVAL '24 hours'
        ORDER BY bucket DESC
    """
    
    # Execute and return
```

### Historical Data (SeaweedFS)

```python
@router.get("/runs/{run_id}/archived-data")
async def get_archived_data(run_id: str):
    """Get archived historical data"""
    
    archived = db.query(ComputedDataset).filter_by(
        experimental_run_id=run_id,
        dataset_type='archived_timeseries'
    ).first()
    
    if not archived:
        raise HTTPException(404, "No archived data")
    
    # Option 1: Return download link
    return {
        "download_url": f"/api/artifacts/{archived.id}/download",
        "format": "hdf5"
    }
    
    # Option 2: Stream data directly
    # with storage.open(archived.minio_path, 'rb') as f:
    #     return StreamingResponse(f, media_type='application/x-hdf5')
```

## Grafana Dashboard Configuration

```yaml
# grafana/provisioning/datasources/datasources.yml
apiVersion: 1

datasources:
  - name: TimescaleDB
    type: postgres
    url: timescaledb:5432
    database: magnetdb_timeseries
    user: magnetdb
    secureJsonData:
      password: ${TIMESCALE_PASSWORD}
    jsonData:
      sslmode: disable
      timescaledb: true

  - name: InfluxDB
    type: influxdb
    url: http://influxdb:8086
    jsonData:
      version: Flux
      organization: lncmi
      defaultBucket: operational_data
      tlsSkipVerify: true
    secureJsonData:
      token: ${INFLUX_TOKEN}
```

## Monitoring & Alerting

### Key Metrics to Monitor

- **Kafka**: Message rate, lag, consumer offset
- **TimescaleDB**: Insert rate, query performance, disk usage
- **Stream Processor**: Processing rate, errors, buffer size
- **Data Quality**: Missing samples, out-of-range values

### Alert Rules

```python
# Example: Alert on sensor failure (no data for X minutes)
query = """
    SELECT device_id, sensor_type,
           MAX(time) as last_seen
    FROM sensor_readings
    GROUP BY device_id, sensor_type
    HAVING MAX(time) < NOW() - INTERVAL '5 minutes'
"""

# Example: Alert on anomaly rate
query = """
    SELECT device_id,
           COUNT(*) as anomaly_count
    FROM device_events
    WHERE event_type = 'anomaly'
    AND time > NOW() - INTERVAL '1 hour'
    GROUP BY device_id
    HAVING COUNT(*) > 10
```

## Performance Considerations

### Kafka Tuning

```yaml
# High throughput configuration
KAFKA_NUM_NETWORK_THREADS: 8
KAFKA_NUM_IO_THREADS: 8
KAFKA_SOCKET_SEND_BUFFER_BYTES: 102400
KAFKA_SOCKET_RECEIVE_BUFFER_BYTES: 102400
KAFKA_SOCKET_REQUEST_MAX_BYTES: 104857600
```

### TimescaleDB Tuning

```sql
-- Increase shared buffers
ALTER SYSTEM SET shared_buffers = '4GB';

-- Increase work memory for aggregations
ALTER SYSTEM SET work_mem = '256MB';

-- Optimize for time-series inserts
ALTER SYSTEM SET synchronous_commit = 'off';  -- For better write performance
```

### Batch vs. Streaming Trade-offs

| Aspect | Batch (Files) | Streaming (Kafka) |
|--------|--------------|-------------------|
| Latency | Hours to days | Seconds |
| Throughput | Very high | High |
| Complexity | Low | Medium |
| Real-time analytics | No | Yes |
| Storage cost | Lower | Higher (hot storage) |
| Query flexibility | Limited (file-based) | High (SQL) |

## Migration Strategy

### Phase 1: Pilot (1-2 months)
- [ ] Deploy Kafka + TimescaleDB in dev
- [ ] Test with one device/sensor
- [ ] Develop stream processor
- [ ] Create basic Grafana dashboard
- [ ] Benchmark performance

### Phase 2: Integration (2-3 months)
- [ ] Integrate with LabVIEW DAQ
- [ ] Deploy to staging
- [ ] Test archival workflow
- [ ] Train operators
- [ ] Document procedures

### Phase 3: Production (3-6 months)
- [ ] Deploy to production
- [ ] Onboard devices incrementally
- [ ] Monitor and optimize
- [ ] Expand to all sensors
- [ ] Full operational use

## Cost-Benefit Analysis

### Benefits
- **Real-time monitoring**: Immediate feedback during experiments
- **Anomaly detection**: Prevent equipment damage
- **Live dashboards**: Better situational awareness
- **Rapid analysis**: No waiting for post-processing
- **Historical queries**: SQL interface to all data

### Costs
- **Infrastructure**: Kafka, TimescaleDB, stream processors
- **Storage**: Hot storage more expensive than cold
- **Complexity**: More moving parts to maintain
- **Development**: New skills required (Kafka, time-series DB)

### ROI Estimate
- Prevent 1-2 equipment failures per year: **€50k-100k saved**
- Reduce debugging time by 30%: **€20k-30k value**
- Enable new research capabilities: **Priceless** 😊

## References

- Kafka Documentation: https://kafka.apache.org/documentation/
- TimescaleDB Documentation: https://docs.timescale.com/
- InfluxDB Documentation: https://docs.influxdata.com/
- Grafana Documentation: https://grafana.com/docs/
- Stream Processing Patterns: https://www.oreilly.com/library/view/streaming-systems/9781491983867/
