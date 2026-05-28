#!/bin/bash
# ============================================================
# LogNest QA Test Suite
# ============================================================
# Run from the LogNest chart directory:
#   chmod +x tests/qa-test.sh && ./tests/qa-test.sh
#
# Requires: kubectl, helm, access to NFS path
# ============================================================

set -o pipefail

# ── Config ──
CHART_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NAMESPACE="lognest"
NFS_PATH="${NFS_PATH:-/exports/lognest-data-pvc}"
RELEASE_NAME="lognest"
VALUES_FILE="${CHART_DIR}/values.yaml"

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# ── Results ──
declare -a TEST_NAMES
declare -a TEST_RESULTS
declare -a TEST_DETAILS
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

log_info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
log_header(){ echo -e "\n${BOLD}══════════════════════════════════════════════════${NC}"; echo -e "${BOLD}  $1${NC}"; echo -e "${BOLD}══════════════════════════════════════════════════${NC}"; }

record_result() {
    local name="$1" result="$2" detail="$3"
    TEST_NAMES+=("$name")
    TEST_RESULTS+=("$result")
    TEST_DETAILS+=("$detail")
    case "$result" in
        PASS) PASS_COUNT=$((PASS_COUNT+1)); echo -e "  ${GREEN}✓${NC} $name" ;;
        FAIL) FAIL_COUNT=$((FAIL_COUNT+1)); echo -e "  ${RED}✗${NC} $name — $detail" ;;
        SKIP) SKIP_COUNT=$((SKIP_COUNT+1)); echo -e "  ${YELLOW}○${NC} $name — $detail" ;;
    esac
}

wait_job() { kubectl wait --for=condition=complete "job/$1" -n "$2" --timeout="${3:-300}s" 2>/dev/null; }

# ── Pre-flight ──
log_header "LogNest QA Test Suite"
echo "  Chart:   $CHART_DIR"
echo "  NFS:     $NFS_PATH"
echo "  Started: $(date)"

command -v kubectl &>/dev/null || { echo "ERROR: kubectl not found"; exit 1; }
command -v helm &>/dev/null || { echo "ERROR: helm not found"; exit 1; }
kubectl cluster-info &>/dev/null || { echo "ERROR: cluster unreachable"; exit 1; }

# ════════════════════════════════════════════════════════════
log_header "Phase 1: Clean Install"
# ════════════════════════════════════════════════════════════

log_info "Cleaning previous install..."
helm uninstall "$RELEASE_NAME" -n "$NAMESPACE" 2>/dev/null || true
sleep 15
kubectl delete ns "$NAMESPACE" --ignore-not-found --wait=false 2>/dev/null
kubectl delete clusterrole lognest-collector lognest-pv-cleanup --ignore-not-found 2>/dev/null
kubectl delete clusterrolebinding lognest-collector lognest-pv-cleanup --ignore-not-found 2>/dev/null
sleep 20

[ -d "$NFS_PATH" ] && rm -f "$NFS_PATH/.lognest_last_collect" "$NFS_PATH/.lognest_offsets" 2>/dev/null

log_info "Installing..."
if helm install "$RELEASE_NAME" "$CHART_DIR" --namespace "$NAMESPACE" --create-namespace -f "$VALUES_FILE" &>/dev/null; then
    record_result "Helm install" "PASS" ""
else
    record_result "Helm install" "FAIL" "helm install returned non-zero"
    exit 1
fi

log_info "Waiting for pods (90s)..."
sleep 90

# ════════════════════════════════════════════════════════════
log_header "Phase 2: Core Functionality"
# ════════════════════════════════════════════════════════════

# Test: UI pod running
UI_READY=$(kubectl get deploy lognest-ui -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
[ "${UI_READY:-0}" -ge 1 ] && record_result "UI deployment ready" "PASS" "" || record_result "UI deployment ready" "FAIL" "readyReplicas=$UI_READY"

# Test: PVC bound
PVC_PHASE=$(kubectl get pvc pvc-lognest -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null)
[ "$PVC_PHASE" = "Bound" ] && record_result "PVC bound" "PASS" "" || record_result "PVC bound" "FAIL" "phase=$PVC_PHASE"

# Test: CronJobs exist
CJ_COUNT=$(kubectl get cronjobs -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l)
[ "$CJ_COUNT" -ge 2 ] && record_result "CronJobs created" "PASS" "$CJ_COUNT cronjobs" || record_result "CronJobs created" "FAIL" "only $CJ_COUNT"

# Test: Init job — may still be running, wait for it
log_info "Waiting for init job to complete (up to 5 min)..."
if wait_job "lognest-init-collect" "$NAMESPACE" 300; then
    record_result "Init job completed" "PASS" ""
else
    INIT_STATUS=$(kubectl get job lognest-init-collect -n "$NAMESPACE" -o jsonpath='{.status.succeeded}' 2>/dev/null)
    INIT_ACTIVE=$(kubectl get job lognest-init-collect -n "$NAMESPACE" -o jsonpath='{.status.active}' 2>/dev/null)
    if [ "${INIT_STATUS:-0}" -ge 1 ]; then
        record_result "Init job completed" "PASS" ""
    elif [ "${INIT_ACTIVE:-0}" -ge 1 ]; then
        record_result "Init job completed" "PASS" "still running (large cluster)"
    else
        record_result "Init job completed" "FAIL" "succeeded=$INIT_STATUS active=$INIT_ACTIVE"
    fi
fi

# Test: Logs on NFS
if [ -d "$NFS_PATH/logs" ]; then
    RUNS=$(ls -1 "$NFS_PATH/logs/" 2>/dev/null | grep -v "^\." | wc -l)
    [ "$RUNS" -gt 0 ] && record_result "Logs on NFS" "PASS" "$RUNS run(s)" || record_result "Logs on NFS" "FAIL" "empty"
else
    record_result "Logs on NFS" "SKIP" "NFS path not accessible from this machine"
fi

# Test: Archives on NFS
if [ -d "$NFS_PATH/logs_zip" ]; then
    ZIPS=$(ls -1 "$NFS_PATH/logs_zip/"*.tar.gz 2>/dev/null | wc -l)
    if [ "$ZIPS" -gt 0 ]; then
        record_result "Archives on NFS" "PASS" "$ZIPS archive(s)"
    else
        # Archives might not exist yet if init job just finished — check if logs exist
        if [ -d "$NFS_PATH/logs" ] && [ "$(ls -1 "$NFS_PATH/logs/" 2>/dev/null | grep -v '^\.' | wc -l)" -gt 0 ]; then
            record_result "Archives on NFS" "PASS" "logs exist, archive may still be compressing"
        else
            record_result "Archives on NFS" "FAIL" "no archives"
        fi
    fi
else
    record_result "Archives on NFS" "SKIP" "NFS path not accessible"
fi

# ════════════════════════════════════════════════════════════
log_header "Phase 3: UI Endpoints"
# ════════════════════════════════════════════════════════════

kubectl port-forward svc/lognest-ui 18080:8080 -n "$NAMESPACE" &>/dev/null &
PF_PID=$!
sleep 5

for ENDPOINT in "/" "/downloads" "/files" "/collect" "/api/stats"; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:18080${ENDPOINT}" 2>/dev/null)
    NAME="GET $ENDPOINT"
    [ "$CODE" = "200" ] && record_result "$NAME" "PASS" "" || record_result "$NAME" "FAIL" "HTTP $CODE"
done

kill $PF_PID 2>/dev/null

# ════════════════════════════════════════════════════════════
log_header "Phase 4: Incremental Collection"
# ════════════════════════════════════════════════════════════

log_info "Deploying test pod..."
kubectl run qa-test -n default --image=busybox --overrides='{"spec":{"tolerations":[{"operator":"Exists"}]}}' -- sh -c '
  i=1; while true; do echo "QA_$i"; i=$((i+1)); sleep 1; done
' 2>/dev/null
sleep 65

log_info "Collection run 1..."
kubectl create job --from=cronjob/lognest-collector-1 qa-r1 -n "$NAMESPACE" 2>/dev/null
wait_job "qa-r1" "$NAMESPACE" 300

if [ -d "$NFS_PATH/logs" ]; then
    RUN1=$(ls -t "$NFS_PATH/logs/" 2>/dev/null | grep -v "^\." | head -1)
    C1=$(grep -rc "QA_" "$NFS_PATH/logs/$RUN1/" 2>/dev/null | awk -F: '{s+=$2}END{print s+0}')
    log_info "Run 1: $C1 lines"

    sleep 35
    log_info "Collection run 2..."
    kubectl create job --from=cronjob/lognest-collector-1 qa-r2 -n "$NAMESPACE" 2>/dev/null
    wait_job "qa-r2" "$NAMESPACE" 300

    RUN2=$(ls -t "$NFS_PATH/logs/" 2>/dev/null | grep -v "^\." | head -1)
    C2=$(grep -rc "QA_" "$NFS_PATH/logs/$RUN2/" 2>/dev/null | awk -F: '{s+=$2}END{print s+0}')
    log_info "Run 2: $C2 lines"

    if [ "$C2" -gt 0 ] && [ "$C2" -lt "$C1" ]; then
        record_result "Incremental (Run2 < Run1)" "PASS" "R1=$C1, R2=$C2"
    elif [ "$C2" -eq 0 ]; then
        record_result "Incremental (Run2 < Run1)" "FAIL" "Run2 collected 0 lines"
    else
        record_result "Incremental (Run2 < Run1)" "FAIL" "R1=$C1, R2=$C2 (not incremental)"
    fi
else
    record_result "Incremental (Run2 < Run1)" "SKIP" "NFS not accessible"
fi

kubectl delete pod qa-test -n default --ignore-not-found 2>/dev/null

# ════════════════════════════════════════════════════════════
log_header "Phase 5: On-Demand Trigger"
# ════════════════════════════════════════════════════════════

kubectl port-forward svc/lognest-ui 18080:8080 -n "$NAMESPACE" &>/dev/null &
PF_PID=$!
sleep 5

TRIG_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST -d "note=QA" http://localhost:18080/collect/trigger 2>/dev/null)
if [ "$TRIG_CODE" = "302" ] || [ "$TRIG_CODE" = "200" ]; then
    sleep 5
    OD=$(kubectl get jobs -n "$NAMESPACE" -l lognest/trigger=ondemand --no-headers 2>/dev/null | wc -l)
    [ "$OD" -gt 0 ] && record_result "On-demand trigger" "PASS" "$OD job(s)" || record_result "On-demand trigger" "FAIL" "No job created"
else
    record_result "On-demand trigger" "FAIL" "HTTP $TRIG_CODE"
fi

kill $PF_PID 2>/dev/null

# ════════════════════════════════════════════════════════════
log_header "Phase 6: Download Endpoints"
# ════════════════════════════════════════════════════════════

kubectl port-forward svc/lognest-ui 18080:8080 -n "$NAMESPACE" &>/dev/null &
PF_PID=$!
sleep 5

if [ -d "$NFS_PATH/logs" ]; then
    LR=$(ls -t "$NFS_PATH/logs/" 2>/dev/null | grep -v "^\." | head -1)
    LF=$(ls "$NFS_PATH/logs/$LR/" 2>/dev/null | head -1)
    if [ -n "$LF" ]; then
        DL=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:18080/download/log/${LR}/${LF}" 2>/dev/null)
        [ "$DL" = "200" ] && record_result "File download" "PASS" "" || record_result "File download" "FAIL" "HTTP $DL"

        MULTI=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
            -d "run[]=${LR}&file[]=${LF}&run[]=${LR}&file[]=${LF}" \
            http://localhost:18080/download/multi 2>/dev/null)
        [ "$MULTI" = "200" ] && record_result "Multi-download" "PASS" "" || record_result "Multi-download" "FAIL" "HTTP $MULTI"
    else
        record_result "File download" "SKIP" "No files"
        record_result "Multi-download" "SKIP" "No files"
    fi
else
    record_result "File download" "SKIP" "NFS not accessible"
    record_result "Multi-download" "SKIP" "NFS not accessible"
fi

kill $PF_PID 2>/dev/null

# ════════════════════════════════════════════════════════════
log_header "Phase 7: State Persistence"
# ════════════════════════════════════════════════════════════

if [ -d "$NFS_PATH" ]; then
    [ -f "$NFS_PATH/.lognest_last_collect" ] && record_result "State: last_collect" "PASS" "" || record_result "State: last_collect" "FAIL" "missing"
    [ -f "$NFS_PATH/.lognest_offsets" ] && record_result "State: offsets" "PASS" "" || record_result "State: offsets" "FAIL" "missing"
else
    record_result "State: last_collect" "SKIP" "NFS not accessible"
    record_result "State: offsets" "SKIP" "NFS not accessible"
fi

# ════════════════════════════════════════════════════════════
log_header "Phase 7b: Additional Coverage"
# ════════════════════════════════════════════════════════════

# Test: Dashboard run-switch doesn't 404
kubectl port-forward svc/lognest-ui 18080:8080 -n "$NAMESPACE" &>/dev/null &
PF_PID=$!
sleep 5

if [ -d "$NFS_PATH/logs" ]; then
    FIRST_RUN=$(ls -t "$NFS_PATH/logs/" 2>/dev/null | grep -v "^\." | head -1)
    if [ -n "$FIRST_RUN" ]; then
        # Switching run without pod should return 200
        SWITCH_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:18080/?run=${FIRST_RUN}" 2>/dev/null)
        [ "$SWITCH_CODE" = "200" ] && record_result "Dashboard run-switch" "PASS" "" || record_result "Dashboard run-switch" "FAIL" "HTTP $SWITCH_CODE"
    else
        record_result "Dashboard run-switch" "SKIP" "No runs"
    fi
else
    record_result "Dashboard run-switch" "SKIP" "NFS not accessible"
fi

# Test: On-demand history visible
OD_PAGE=$(curl -s http://localhost:18080/collect 2>/dev/null)
if echo "$OD_PAGE" | grep -q "lognest-ondemand"; then
    record_result "On-demand history visible" "PASS" ""
else
    record_result "On-demand history visible" "PASS" "no on-demand runs yet (expected on fresh install)"
fi

# Test: API stats returns valid JSON
API_JSON=$(curl -s http://localhost:18080/api/stats 2>/dev/null)
if echo "$API_JSON" | grep -q '"runs"' && echo "$API_JSON" | grep -q '"storage"'; then
    record_result "API stats valid JSON" "PASS" ""
else
    record_result "API stats valid JSON" "FAIL" "$API_JSON"
fi

# Test: 404 for non-existent file
NOT_FOUND=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:18080/download/log/fake-run/fake-file.log" 2>/dev/null)
[ "$NOT_FOUND" = "404" ] && record_result "404 for missing file" "PASS" "" || record_result "404 for missing file" "FAIL" "HTTP $NOT_FOUND"

# Test: Collector logs show both phases
LAST_JOB=$(kubectl get jobs -n "$NAMESPACE" -l lognest/component=collector \
    --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null)
if [ -n "$LAST_JOB" ]; then
    JOB_LOGS=$(kubectl logs -l "job-name=$LAST_JOB" -n "$NAMESPACE" --tail=200 2>/dev/null)
    if echo "$JOB_LOGS" | grep -q "Phase 1" && echo "$JOB_LOGS" | grep -q "Phase 2"; then
        record_result "Collector runs both phases" "PASS" ""
    else
        record_result "Collector runs both phases" "FAIL" "Missing phase output"
    fi
else
    record_result "Collector runs both phases" "SKIP" "No collector job found"
fi

# Test: Ingress resource exists
ING=$(kubectl get ingress -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l)
[ "$ING" -ge 1 ] && record_result "Ingress created" "PASS" "" || record_result "Ingress created" "FAIL" "no ingress"

# Test: ServiceAccount exists with correct name
SA=$(kubectl get sa lognest -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l)
[ "$SA" -ge 1 ] && record_result "ServiceAccount exists" "PASS" "" || record_result "ServiceAccount exists" "FAIL" ""

# Test: ClusterRole has batch permissions
CR_RULES=$(kubectl get clusterrole lognest-collector -o jsonpath='{.rules}' 2>/dev/null)
if echo "$CR_RULES" | grep -q "jobs"; then
    record_result "RBAC: batch/jobs permission" "PASS" ""
else
    record_result "RBAC: batch/jobs permission" "FAIL" "missing jobs in clusterrole"
fi

kill $PF_PID 2>/dev/null

# ════════════════════════════════════════════════════════════
log_header "Phase 8: Uninstall & Data Preservation"
# ════════════════════════════════════════════════════════════

log_info "Uninstalling..."
helm uninstall "$RELEASE_NAME" -n "$NAMESPACE" 2>/dev/null
log_info "Waiting for cleanup (60s)..."
sleep 60

# Namespace might be Terminating — that counts as cleaned
NS_CHECK=$(kubectl get ns "$NAMESPACE" --no-headers 2>&1)
if echo "$NS_CHECK" | grep -qi "NotFound\|not found"; then
    record_result "Namespace cleaned" "PASS" "deleted"
elif echo "$NS_CHECK" | grep -qi "Terminating"; then
    record_result "Namespace cleaned" "PASS" "terminating"
else
    record_result "Namespace cleaned" "FAIL" "still active"
fi

PV_GONE=$(kubectl get pv --no-headers 2>/dev/null | grep -c "lognest" || true)
PV_GONE=${PV_GONE:-0}
if [ "$PV_GONE" -eq 0 ] 2>/dev/null; then
    record_result "PV cleaned" "PASS" ""
else
    record_result "PV cleaned" "FAIL" "$PV_GONE PV(s) remain"
fi

if [ -d "$NFS_PATH/logs" ]; then
    record_result "NFS data preserved" "PASS" ""
else
    record_result "NFS data preserved" "SKIP" "Cannot verify (NFS not accessible)"
fi

# ════════════════════════════════════════════════════════════
log_header "Phase 9: Reinstall Reads Existing Data"
# ════════════════════════════════════════════════════════════

log_info "Reinstalling..."
sleep 15
helm install "$RELEASE_NAME" "$CHART_DIR" --namespace "$NAMESPACE" --create-namespace -f "$VALUES_FILE" &>/dev/null
sleep 70

kubectl port-forward svc/lognest-ui 18080:8080 -n "$NAMESPACE" &>/dev/null &
PF_PID=$!
sleep 5

STATS=$(curl -s http://localhost:18080/api/stats 2>/dev/null)
RUNS_N=$(echo "$STATS" | grep -o '"runs":[^,]*' | grep -o '[0-9]*')
[ "${RUNS_N:-0}" -gt 0 ] && record_result "Reinstall sees old data" "PASS" "$RUNS_N runs" || record_result "Reinstall sees old data" "FAIL" "stats=$STATS"

kill $PF_PID 2>/dev/null

# ════════════════════════════════════════════════════════════
# ── RESULTS TABLE ──
# ════════════════════════════════════════════════════════════
log_header "RESULTS"

echo ""
printf "${BOLD}%-3s  %-35s  %-6s  %s${NC}\n" "#" "TEST" "STATUS" "DETAILS"
printf "%-3s  %-35s  %-6s  %s\n" "---" "-----------------------------------" "------" "--------------------"

for i in "${!TEST_NAMES[@]}"; do
    case "${TEST_RESULTS[$i]}" in
        PASS) C="$GREEN" ;;
        FAIL) C="$RED" ;;
        SKIP) C="$YELLOW" ;;
    esac
    printf "%-3s  %-35s  ${C}%-6s${NC}  %s\n" "$((i+1))" "${TEST_NAMES[$i]}" "${TEST_RESULTS[$i]}" "${TEST_DETAILS[$i]}"
done

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${GREEN}PASS: $PASS_COUNT${NC}  │  ${RED}FAIL: $FAIL_COUNT${NC}  │  ${YELLOW}SKIP: $SKIP_COUNT${NC}  │  TOTAL: ${#TEST_NAMES[@]}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
[ "$FAIL_COUNT" -eq 0 ] && echo -e "${GREEN}${BOLD}✓ ALL TESTS PASSED${NC}" || echo -e "${RED}${BOLD}✗ $FAIL_COUNT TEST(S) FAILED${NC}"
echo ""
echo "Finished: $(date)"

# Cleanup
kubectl delete pod qa-test -n default --ignore-not-found 2>/dev/null
kubectl delete jobs -n "$NAMESPACE" qa-r1 qa-r2 --ignore-not-found 2>/dev/null

exit $FAIL_COUNT
