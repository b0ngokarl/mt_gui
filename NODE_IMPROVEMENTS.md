# Node Management Improvements

## Issues Fixed

### 1. Favorite Flag Preservation
- **Problem**: Favorite flags (★) were being overwritten during node refresh
- **Solution**: Modified `update_nodes_table()` to preserve existing favorite flags
- **Implementation**: 
  - Checks existing table data before updating
  - Only updates node data if newer timestamp detected
  - Preserves user-set favorites and remarks

### 2. Node Limit Warning
- **Problem**: Users weren't aware when node lists might be truncated at 100 nodes
- **Solution**: Added warning when 100+ nodes detected
- **Implementation**:
  - Displays warning about potential CLI/device limitations
  - Suggests using `--limit 0` parameter for full list
  - Shows detailed update statistics

### 3. Smart Data Merging
- **Problem**: Complete replacement of node data lost user preferences
- **Solution**: Implemented intelligent merging based on timestamps
- **Features**:
  - Compares `LastHeard` timestamps to determine freshness
  - Only updates with newer data
  - Preserves user remarks and favorite status
  - Reports update statistics (new/updated/preserved)

## Key Improvements

### Data Preservation Strategy
```
For each node refresh:
1. Check if node exists in table
2. Compare LastHeard timestamps
3. Update ONLY if new data is newer
4. Always preserve:
   - Favorite flags (★)
   - User remarks
   - Manual data entries
```

### Update Statistics
The system now reports:
- **New nodes**: Completely new discoveries
- **Updated nodes**: Existing nodes with newer data
- **Preserved nodes**: Existing nodes with current/newer data
- **Total nodes**: Current table count

### CLI Limitation Detection
- Warns when node count reaches typical CLI limits (≥100)
- Suggests CLI parameters to bypass limits
- Helps users understand why some nodes might be missing

## User Experience Benefits

1. **No More Lost Favorites**: Starred nodes stay starred through refreshes
2. **Preserved Remarks**: Custom notes survive node updates
3. **Smarter Updates**: Only newer data overwrites existing data
4. **Limit Awareness**: Clear warnings about potential truncation
5. **Detailed Feedback**: Know exactly what changed during refresh

## Technical Implementation

- **Timestamp Parsing**: Handles multiple date/time formats
- **Fallback Logic**: Graceful handling of missing timestamps
- **Memory Efficient**: Updates in-place rather than full replacement
- **Error Resistant**: Continues operation even with malformed data

This ensures your node list behaves more like a persistent database rather than a volatile refresh-and-replace system.
