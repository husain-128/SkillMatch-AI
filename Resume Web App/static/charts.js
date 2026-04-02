function renderStatusChart(canvasId, statusCounts) {
    var canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === 'undefined') {
        return;
    }
    var labels = Object.keys(statusCounts || {});
    var values = labels.map(function (key) { return statusCounts[key]; });
    var colorMap = {
        Applied: '#FFC107',
        Interview: '#4CAF50',
        Shortlisted: '#2196F3',
        Selected: '#E91E63',
        Rejected: '#F44336'
    };
    var colors = labels.map(function (label) {
        return colorMap[label] || '#9E9E9E';
    });

    new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Applications',
                data: values,
                backgroundColor: colors
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { precision: 0 }
                }
            }
        }
    });
}
