import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, PrivateRoute } from "./auth/AuthContext";
import { AppShell } from "./components/AppShell";
import { ActivityCreatePage } from "./pages/ActivityCreatePage";
import { AssessmentReviewPage } from "./pages/AssessmentReviewPage";
import { BlueprintPage } from "./pages/BlueprintPage";
import { LoginPage } from "./pages/LoginPage";
import {
  SubmissionProgressPage,
  SubmissionStartPage,
} from "./pages/SubmissionPage";

export function AppRoutes() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<PrivateRoute />}>
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/activities/new" replace />} />
            <Route path="/activities/new" element={<ActivityCreatePage />} />
            <Route path="/activities/:activityId/blueprint" element={<BlueprintPage />} />
            <Route path="/activities/:activityId/submission" element={<SubmissionStartPage />} />
            <Route path="/submissions/:submissionId" element={<SubmissionProgressPage />} />
            <Route path="/submissions/:submissionId/review" element={<AssessmentReviewPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/activities/new" replace />} />
      </Routes>
    </AuthProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}

