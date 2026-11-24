/** 服务装配：整个前端只在这里 new 一次。 */
import { HttpClient } from "./HttpClient";
import { StockService } from "./StockService";
import { EventService } from "./EventService";
import { ReportService } from "./ReportService";
import { MaintenanceService } from "./MaintenanceService";
import { ChatService } from "./ChatService";
import { AlertService } from "./AlertService";
import { IndustryService } from "./IndustryService";
import { TaskService } from "./TaskService";

const http = new HttpClient("/api");

export const services = {
  http,
  stocks: new StockService(http),
  events: new EventService(http),
  reports: new ReportService(http),
  maintenance: new MaintenanceService(http),
  chat: new ChatService(http),
  alerts: new AlertService(http),
  industries: new IndustryService(http),
  tasks: new TaskService(http),
};

export {
  StockService, EventService, ReportService, MaintenanceService,
  ChatService, AlertService, IndustryService, TaskService, HttpClient,
};
