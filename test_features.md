# New Features Added to Meshtastic Client GUI

## 🌟 Favorites System
- **Favorite Column**: Added a new "Fav" column (first column) in the discovered nodes table
- **Click to Favorite**: Click on any cell in the "Fav" column to toggle favorite status
- **Visual Indicator**: Favorite nodes show a ★ (star) symbol
- **Persistent Storage**: Favorites are saved to `favorite_nodes.json` and restored on app restart

## 🗂️ Column Sorting
- **All Columns Sortable**: Click on any column header to sort the table
- **Ascending/Descending**: Click again to reverse sort order
- **Multiple Columns**: Sort by any column including:
  - Favorites (★ shows at top when sorted)
  - Node Number, User, ID, AKA
  - Hardware, Role, Location data
  - Battery, Channel utilization, Signal strength
  - Last heard timestamps

## 🗑️ Node Deletion
- **Delete Selected Button**: New "Delete Selected" button in the node controls
- **Row Selection**: Click on any row to select a node
- **Confirmation Dialog**: Confirms before deletion with clear warning
- **Complete Cleanup**: Removes node from:
  - Discovered nodes list
  - Favorites (if favorited) 
  - User remarks
  - Target selection dropdown
- **Persistence**: Changes are automatically saved to all JSON files

## 💾 Enhanced Data Persistence
Now saves to 4 separate JSON files:
1. `meshtastic_settings.json` - Connection settings and manual targets
2. `discovered_nodes.json` - All discovered node data with timestamps  
3. `node_remarks.json` - User-editable remarks for each node
4. `favorite_nodes.json` - List of favorited node IDs

## 🔄 Updated Table Structure
- **19 Columns Total**: Added "Fav" column at the beginning
- **Optimized Layout**: Favorite column is narrow (40px width)
- **Smart Sorting**: Temporarily disables sorting during table updates to prevent conflicts
- **Click Handling**: Different behavior for favorite column (toggle) vs remark column (edit)

## 🎯 How to Use New Features

### Setting Favorites:
1. Run "Refresh Nodes" to populate the table with your discovered nodes
2. Click in the "Fav" column for any node you want to favorite
3. A ★ will appear - click again to remove favorite
4. Favorites persist across app restarts

### Sorting the Table:
1. Click any column header to sort by that column
2. Click again to reverse the sort order
3. Try sorting by "Fav" to see all favorites at the top
4. Sort by "Last Heard" or "Last Seen by Client" to see most recent activity

### Deleting Nodes:
1. Click on a row to select a node
2. Click "Delete Selected" button  
3. Confirm the deletion in the dialog
4. Node is completely removed from GUI (but not from actual network)

All changes are automatically saved, so your preferences are preserved between sessions!
