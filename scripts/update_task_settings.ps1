# Update scheduled task settings for TV-collection: set to ignore new instances and 3 hour execution limit
$taskName = 'TV-collection'
try {
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3)
    Set-ScheduledTask -TaskName $taskName -Settings $settings
    Write-Output "Updated settings for task: $taskName"
    $t = Get-ScheduledTask -TaskName $taskName
    $s = $t.Settings
    Write-Output "MultipleInstances: $($s.MultipleInstances)"
    Write-Output "ExecutionTimeLimit: $($s.ExecutionTimeLimit)"
} catch {
    Write-Error "Error updating task: $_"
    exit 1
}
