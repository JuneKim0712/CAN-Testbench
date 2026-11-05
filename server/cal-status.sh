#!/usr/bin/env bash
# ==============================================================================
# CalSol Testbench Server: Active Boards and Mutex Status Inspector
# ==============================================================================

echo "================================================================================"
echo "                   CalSol CAN Testbench - Hardware Status                       "
echo "================================================================================"
printf "%-22s %-16s %-12s %-20s\n" "BOARD SYM" "DEVICE" "STATUS" "CURRENT USER / LOCK"
echo "--------------------------------------------------------------------------------"

LOCK_DIRS=("/var/lock" "${HOME}/.calsol/locks")

for dev in /dev/esp32_* /dev/calsol_*; do
    [ ! -e "$dev" ] && continue
    board_name="$(basename "$dev")"
    target_dev="$(readlink -f "$dev")"

    # Check lock status
    status="IDLE"
    lock_info="-"

    for ldir in "${LOCK_DIRS[@]}"; do
        lock_file="${ldir}/calsol_${board_name}.lock"
        if [ -f "$lock_file" ]; then
            # Test if lock is currently held
            if ! flock -n "$lock_file" -c "true" 2>/dev/null; then
                status="LOCKED"
                owner=$(fuser "$lock_file" 2>/dev/null | xargs -n1 ps -o user= -p 2>/dev/null | head -n 1)
                lock_info="${owner:-active_process}"
            fi
        fi
    done

    printf "%-22s %-16s %-12s %-20s\n" "$board_name" "$target_dev" "$status" "$lock_info"
done
echo "================================================================================"
