/** 服务装配：整个前端只在这里 new 一次。 */
import { HttpClient } from "./HttpClient";
import { StockService } from "./StockService";
import { EventService } from "./EventService";
import { ReportService } from "./ReportService";

const http = new HttpClient("/api");

export const services = {
  http,
  stocks: new StockService(http),
  events: new EventService(http),
  reports: new ReportService(http),
};

export { StockService, EventService, ReportService, HttpClient };
