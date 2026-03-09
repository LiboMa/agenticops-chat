# H200×8 GPU Benchmark Report: Qwen2.5 Models (FP8)

**Report Date:** February 4, 2026  
**Hardware Configuration:** NVIDIA H200 × 8 GPUs  
**Precision:** FP8  
**Models Tested:** Qwen2.5-72B, Qwen2.5-32B, Qwen2.5-14B  
**Test Parameters:** Input: 10,000 tokens, Output: 800 tokens (32B/14B) | Input: 20,000 tokens, Output: 1,000 tokens (72B)

---

## Executive Summary

This report analyzes the performance of H200×8 GPU configuration running Qwen2.5 models at FP8 precision to evaluate capacity for QPS 40-200 workloads.

### Key Findings

| Model | Max Sustainable QPS | Recommended QPS Range | Optimal Concurrency |
|-------|---------------------|----------------------|---------------------|
| **Qwen2.5-72B** | ~0.84 | 0.5-0.8 | 50 |
| **Qwen2.5-32B** | ~3.65 | 2.5-3.5 | 90-120 |
| **Qwen2.5-14B** | ~12.2 | 8-12 | 120-200 |

### Capacity Assessment for QPS 40-200 Target

⚠️ **Critical Finding:** A single H200×8 node **cannot** achieve QPS 40-200 with any of the tested Qwen models at the tested input/output lengths.

| Target QPS | 72B Nodes Required | 32B Nodes Required | 14B Nodes Required |
|------------|-------------------|-------------------|-------------------|
| 40 | ~48 | ~12 | ~4 |
| 100 | ~120 | ~29 | ~9 |
| 200 | ~240 | ~55 | ~17 |

---

## Detailed Performance Analysis

### 1. Qwen2.5-72B Performance

**Test Configuration:** 20K input tokens, 1K output tokens, Concurrency: 50

```
┌─────────────────────────────────────────────────────────────────┐
│                    Qwen2.5-72B Performance                       │
├─────────────────────────────────────────────────────────────────┤
│  Request Throughput:        0.84 req/s                          │
│  Output Token Throughput:   838 tok/s                           │
│  Peak Output Throughput:    2,300 tok/s                         │
│  Total Token Throughput:    17,606 tok/s                        │
├─────────────────────────────────────────────────────────────────┤
│  LATENCY METRICS                                                │
│  ─────────────────                                              │
│  Mean TTFT:                 4,189 ms                            │
│  Median TTFT:               2,596 ms                            │
│  P99 TTFT:                  34,542 ms                           │
│  Mean TPOT:                 55.43 ms                            │
│  Median TPOT:               57.18 ms                            │
│  P99 TPOT:                  58.68 ms                            │
└─────────────────────────────────────────────────────────────────┘
```

**Analysis:**
- The 72B model is heavily memory-bound with long context (20K tokens)
- TTFT is high due to prefill computation overhead
- Consistent TPOT indicates stable generation phase
- Not suitable for high-throughput scenarios

---

### 2. Qwen2.5-32B Performance

**Test Configuration:** 10K input tokens, 800 output tokens

#### Performance by Concurrency Level

| Concurrency | Throughput (req/s) | Output tok/s | Mean TTFT (ms) | Mean TPOT (ms) | P99 TTFT (ms) |
|-------------|-------------------|--------------|----------------|----------------|---------------|
| 30 | 2.56 | 2,049 | 1,411 | 12.72 | 4,387 |
| 60 | 3.16 | 2,525 | 1,649 | 21.10 | 9,184 |
| 90 | 3.31 | 2,644 | 2,359 | 30.22 | 14,527 |
| 120 | 3.50 | 2,802 | 3,387 | 37.13 | 19,995 |
| 200 | 3.65 | 2,918 | 7,846 | 55.80 | 35,011 |

```
Qwen2.5-32B: Throughput vs Concurrency
                                                                    
  Throughput │                                              ●
  (req/s)    │                                    ●
             │                          ●
    3.5 ─────┼──────────────────────────────────────────────
             │                ●
    3.0 ─────┼────────────────────────────────────────────
             │      ●
    2.5 ─────┼────────────────────────────────────────────
             │
    2.0 ─────┼────────────────────────────────────────────
             └────┬────┬────┬────┬────┬────┬────┬────┬────
                 30   60   90  120  150  180  200
                           Concurrency

Qwen2.5-32B: Latency vs Concurrency
                                                                    
  TTFT (ms)  │                                              ●
             │                                              
   8000 ─────┼──────────────────────────────────────────────
             │
   6000 ─────┼──────────────────────────────────────────────
             │
   4000 ─────┼──────────────────────────────────────────────
             │                                    ●
   2000 ─────┼────────────────────────●───────────────────
             │      ●         ●
      0 ─────┼────────────────────────────────────────────
             └────┬────┬────┬────┬────┬────┬────┬────┬────
                 30   60   90  120  150  180  200
                           Concurrency
```

**Analysis:**
- Throughput plateaus around 3.5-3.7 req/s regardless of concurrency
- TTFT increases dramatically at high concurrency (queuing effect)
- Optimal operating point: **Concurrency 60-90** for balanced latency/throughput
- TPOT remains relatively stable, indicating consistent generation speed

---

### 3. Qwen2.5-14B Performance

**Test Configuration:** 10K input tokens, 800 output tokens

#### Performance by Concurrency Level

| Concurrency | Throughput (req/s) | Output tok/s | Mean TTFT (ms) | Mean TPOT (ms) | P99 TTFT (ms) |
|-------------|-------------------|--------------|----------------|----------------|---------------|
| 30 | 3.85 | 3,081 | 966 | 8.42 | 2,742 |
| 60 | 8.69 | 6,953 | 177 | 7.99 | 379 |
| 90 | 9.42 | 7,535 | 295 | 10.91 | 517 |
| 120 | 10.82 | 8,653 | 340 | 12.38 | 735 |
| 200 | 12.20 | 9,763 | 558 | 17.49 | 1,190 |

```
Qwen2.5-14B: Throughput vs Concurrency
                                                                    
  Throughput │                                              ●
  (req/s)    │                                    ●
             │                          ●
   12.0 ─────┼──────────────────────────────────────────────
             │                ●
   10.0 ─────┼────────────────────────────────────────────
             │
    8.0 ─────┼────────────────────────────────────────────
             │
    6.0 ─────┼────────────────────────────────────────────
             │      ●
    4.0 ─────┼────────────────────────────────────────────
             └────┬────┬────┬────┬────┬────┬────┬────┬────
                 30   60   90  120  150  180  200
                           Concurrency
```

**Analysis:**
- Excellent scaling up to concurrency 200
- Best latency profile at concurrency 60 (177ms mean TTFT)
- Throughput continues to improve with higher concurrency
- Most efficient model for high-throughput scenarios

---

## Model Comparison

### Throughput Comparison (Peak Performance)

```
                    Peak Request Throughput (req/s)
                    
  Qwen2.5-14B  ████████████████████████████████████████████████  12.20
  Qwen2.5-32B  ██████████████                                     3.65
  Qwen2.5-72B  ███                                                0.84
               └────┬────┬────┬────┬────┬────┬────┬────┬────┬────
                   0    2    4    6    8   10   12   14
```

### Output Token Throughput Comparison

```
                    Peak Output Token Throughput (tok/s)
                    
  Qwen2.5-14B  ████████████████████████████████████████████████  9,763
  Qwen2.5-32B  ██████████████                                    2,918
  Qwen2.5-72B  ████                                                838
               └────┬────┬────┬────┬────┬────┬────┬────┬────┬────
                   0   2K   4K   6K   8K  10K
```

### Latency Comparison (at Optimal Concurrency)

| Model | Optimal Concurrency | Mean TTFT | Mean TPOT | P99 TTFT |
|-------|---------------------|-----------|-----------|----------|
| 72B | 50 | 4,189 ms | 55.43 ms | 34,542 ms |
| 32B | 60 | 1,649 ms | 21.10 ms | 9,184 ms |
| 14B | 60 | 177 ms | 7.99 ms | 379 ms |

---

## Capacity Planning for QPS 40-200

### Scenario Analysis

#### Scenario 1: QPS 40 Target

| Model | Single Node QPS | Nodes Required | Total GPUs |
|-------|-----------------|----------------|------------|
| 72B | 0.84 | 48 | 384 |
| 32B | 3.65 | 11 | 88 |
| 14B | 12.20 | 4 | 32 |

#### Scenario 2: QPS 100 Target

| Model | Single Node QPS | Nodes Required | Total GPUs |
|-------|-----------------|----------------|------------|
| 72B | 0.84 | 120 | 960 |
| 32B | 3.65 | 28 | 224 |
| 14B | 12.20 | 9 | 72 |

#### Scenario 3: QPS 200 Target

| Model | Single Node QPS | Nodes Required | Total GPUs |
|-------|-----------------|----------------|------------|
| 72B | 0.84 | 239 | 1,912 |
| 32B | 3.65 | 55 | 440 |
| 14B | 12.20 | 17 | 136 |

---

## Testing Methodology Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    BENCHMARK TESTING FLOW                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │   1. Environment Setup         │
              │   - H200×8 GPU Configuration   │
              │   - FP8 Precision Mode         │
              │   - vLLM Backend               │
              └───────────────┬───────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │   2. Model Loading             │
              │   - Qwen2.5-72B/32B/14B        │
              │   - Tensor Parallelism: 8      │
              └───────────────┬───────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │   3. Stress Test Execution     │
              │   - 500 requests per test      │
              │   - Random dataset             │
              │   - Variable concurrency       │
              │     (30, 60, 90, 120, 200)     │
              └───────────────┬───────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │   4. Metrics Collection        │
              │   - Request throughput         │
              │   - Token throughput           │
              │   - TTFT (Time to First Token) │
              │   - TPOT (Time per Output Tok) │
              │   - ITL (Inter-token Latency)  │
              └───────────────┬───────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │   5. Statistical Analysis      │
              │   - Mean, Median, P99          │
              │   - Peak throughput            │
              │   - Variance analysis          │
              └───────────────────────────────┘
```

---

## Statistical Summary

### Qwen2.5-32B Detailed Statistics (Concurrency 90)

| Metric | Mean | Median | P99 | Variance |
|--------|------|--------|-----|----------|
| TTFT (ms) | 2,359 | 1,186 | 14,527 | High |
| TPOT (ms) | 30.22 | 32.10 | 32.91 | Low |
| ITL (ms) | 30.22 | 15.12 | 151.21 | Medium |

### Qwen2.5-14B Detailed Statistics (Concurrency 90)

| Metric | Mean | Median | P99 | Variance |
|--------|------|--------|-----|----------|
| TTFT (ms) | 295 | 333 | 517 | Low |
| TPOT (ms) | 10.91 | 11.19 | 11.32 | Very Low |
| ITL (ms) | 10.98 | 11.07 | 16.31 | Very Low |

---

## Recommendations

### For QPS 40-200 Target Workloads

1. **Model Selection:**
   - **Qwen2.5-14B** is the most cost-effective choice for high-throughput scenarios
   - **Qwen2.5-32B** offers better quality with moderate throughput
   - **Qwen2.5-72B** should only be used for quality-critical, low-volume workloads

2. **Infrastructure Sizing:**
   - For QPS 40: Minimum 4 H200×8 nodes with Qwen2.5-14B
   - For QPS 100: Minimum 9 H200×8 nodes with Qwen2.5-14B
   - For QPS 200: Minimum 17 H200×8 nodes with Qwen2.5-14B

3. **Concurrency Settings:**
   - **14B:** Optimal at 60-120 concurrency for best latency/throughput balance
   - **32B:** Optimal at 60-90 concurrency to avoid TTFT degradation
   - **72B:** Keep at 50 concurrency to maintain acceptable latency

4. **Latency Considerations:**
   - If P99 TTFT < 1s is required, use Qwen2.5-14B at concurrency ≤ 120
   - If P99 TTFT < 10s is acceptable, Qwen2.5-32B at concurrency ≤ 90 is viable

### Performance Optimization Tips

1. **Reduce Input Length:** Shorter prompts significantly improve TTFT
2. **Batch Similar Requests:** Group requests with similar lengths
3. **Use Prefix Caching:** Enable for repeated prompt patterns
4. **Consider Speculative Decoding:** Can improve throughput for 72B model

---

## Anomalies and Observations

1. **72B Model Bottleneck:** The 72B model shows severe throughput limitations due to:
   - Large KV cache requirements (20K context)
   - Memory bandwidth saturation
   - High prefill computation time

2. **14B Scaling Efficiency:** The 14B model shows near-linear scaling up to 200 concurrency, indicating:
   - Efficient memory utilization
   - Good compute/memory balance
   - Room for further scaling

3. **32B Sweet Spot:** The 32B model plateaus around 3.5 req/s regardless of concurrency, suggesting:
   - Memory bandwidth limitation
   - Optimal operating point at 60-90 concurrency

---

## Appendix: Raw Data Summary

### Test Environment
- **GPU:** NVIDIA H200 × 8
- **Precision:** FP8
- **Backend:** vLLM (OpenAI-compatible endpoint)
- **Test Tool:** vLLM Benchmark Suite
- **Requests per Test:** 500
- **Dataset:** Random (synthetic)

### Test Matrix

| Model | Input Tokens | Output Tokens | Concurrency Levels |
|-------|--------------|---------------|-------------------|
| 72B | 20,000 | 1,000 | 50 |
| 32B | 10,000 | 800 | 30, 60, 90, 120, 200 |
| 14B | 10,000 | 800 | 30, 60, 90, 120, 200 |

---

*Report generated from benchmark data collected on February 3-4, 2026*
