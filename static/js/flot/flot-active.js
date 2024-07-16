(function ($) {
    "use strict";

    // Fungsi untuk memformat nama hari
    function formatDay(dayIndex) {
        var days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
        return days[dayIndex - 1];
    }

    // Fungsi untuk mendapatkan data dari server
    function getData() {
        return $.ajax({
            url: '/get_barchart_data',
            method: 'GET',
            dataType: 'json'
        });
    }

    // Render chart dengan data dari server
    getData().done(function (response) {
        var data1 = response.motor.map(function (value, index) {
            return [index + 1, value];
        });

        var data2 = response.mobil.map(function (value, index) {
            return [index + 1, value];
        });

        var barData = [{
            label: "Motor",
            data: data1,
            color: "#FFA27F"
        }, {
            label: "Mobil",
            data: data2,
            color: "#01c0c8"
        }];

        $("#bar-chart")[0] && $.plot($("#bar-chart"), barData, {
            series: {
                bars: {
                    show: !0,
                    barWidth: .3,
                    order: 1,
                    fill: 1
                }
            },
            grid: {
                borderWidth: 1,
                borderColor: "#eee",
                show: !0,
                hoverable: !0,
                clickable: !0
            },
            yaxis: {
                tickColor: "#eee",
                tickDecimals: 0,
                font: {
                    lineHeight: 50,
                    style: "normal",
                    color: "#000000"
                },
                shadowSize: 0
            },
            xaxis: {
                tickColor: "#fff",
                tickDecimals: 0,
                font: {
                    lineHeight: 14,
                    style: "normal",
                    color: "#000000"
                },
                shadowSize: 0,
                ticks: [[1, "Monday"], [2, "Tuesday"], [3, "Wednesday"], [4, "Thursday"], [5, "Friday"], [6, "Saturday"], [7, "Sunday"]]
            },
            legend: {
                container: ".flc-bar",
                backgroundOpacity: .5,
                noColumns: 0,
                backgroundColor: "white",
                lineWidth: 0
            }
        });

        $(".flot-chart")[0] && $(".flot-chart").bind("plothover", function (event, pos, item) {
            if (item) {
                var y = Math.round(item.datapoint[1]);  // Mengubah nilai menjadi integer
                $(".flot-tooltip").html(item.series.label + " = " + y).css({
                    top: item.pageY + 5,
                    left: item.pageX + 5
                }).show();
            } else {
                $(".flot-tooltip").hide();
            }
        });

        $("<div class='flot-tooltip' class='chart-tooltip'></div>").appendTo("body");
    });
})(jQuery);
